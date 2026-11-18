#!/usr/bin/env python3
"""
outreach_engine.py — FU FOIA core (the Follow-Up FOIA system), shared by both editions

The engine form of:
  - Omni-Channel Legal Service & Outreach Engine for OsintNeoAi
    (omnichannel_legal_service.py @55cfacb)
  - Anonymous FOIA Dispatch Engine (foia_dispatch_engine.py @55cfacb)
  - fax_hardmail_dispatch_v2.py (real FaxBetter / Lob / SMTP endpoints)

Identity comes from the loaded variant settings — an anonymous unit
identity (FUFOIA-Anonymous) or a signed personal identity
(FUFOIA-Public). The core itself carries no identity.

Hard rules (user directive, 2026-11-18):
  1. ALL email comes from the From address in the loaded settings.
     No other From.
  2. reason_for_contact + requested_action are VERBATIM. Stored once,
     SHA-256 hashed, and must appear byte-for-byte in every draft.
     Escalation changes approach / audience / channel — NEVER the ask.
  3. NOTHING is sent without the user approving the exact copy.
     Approval is bound to the SHA-256 of the approved draft text.
  4. NO fabricated confirmations. Fax/mail adapters return
     status="skipped_no_key" until the user wires a paid account.
     A confirmation/tracking number exists only if a provider returns it.
  5. Escalation clock: 60 minutes per level. A reply stops the clock,
     is parsed for a named human / referral, and re-aims the next
     window at that human.
  6. Recipients must be verified from the target's published directions
     or marked TO_VERIFY. The engine refuses an approval packet for a
     TO_VERIFY recipient. (The original invented director@/foia@ addresses;
     this version does not.)

Modes:
  --dry-run (default): build drafts, verify verbatim, write approval packets.
                       Sends nothing, ever.
  --send-packet:       print the approved send packet for a level so the
                       operator (Neo, via the Gmail connector) can send the
                       exact approved copy. Still sends nothing itself.

Usage:
  python3 outreach_engine.py --case ../cases/google-accounts-001/case.json --dry-run
  python3 outreach_engine.py --case <case.json> --level 2 --dry-run
  python3 outreach_engine.py --parse-reply "<reply text>"
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("America/Los_Angeles")
except Exception:
    LOCAL_TZ = timezone(timedelta(hours=-8))

ROOT = Path(__file__).resolve().parent.parent

def _load_settings() -> tuple[dict, dict, Path]:
    """Variants are settings, not forks. --variant <name> loads
    variants/<name>/settings.json; --settings <path> loads any settings file.
    Default: the repo-root settings of whichever edition repo this core sits in."""
    argv = sys.argv[1:]
    variant = "public"
    settings_path = None
    for i, a in enumerate(argv):
        if a == "--variant" and i + 1 < len(argv):
            variant = argv[i + 1]
        if a == "--settings" and i + 1 < len(argv):
            settings_path = Path(argv[i + 1])
    variant_dir = ROOT / "variants" / variant
    if settings_path is None:
        if (variant_dir / "settings.json").exists():
            settings_path = variant_dir / "settings.json"
        elif (ROOT / "settings.json").exists():
            # Single-variant repo layout (FUFOIA-Public / FUFOIA-Anonymous):
            # settings live at the repo root and the repo root is the variant dir.
            settings_path = ROOT / "settings.json"
            variant_dir = ROOT
        else:
            settings_path = variant_dir / "settings.json"
    else:
        variant_dir = settings_path.resolve().parent
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    return data["identity"], data["engine"], variant_dir

IDENTITY, ENGINE_CFG, VARIANT_DIR = _load_settings()
LOG_PATH = VARIANT_DIR / "logs" / "dispatch_log.jsonl"
REPLY_WINDOW_MIN = ENGINE_CFG["escalation"]["reply_window_minutes"]


def now_iso():
    n = datetime.now(timezone.utc)
    return {"utc": n.isoformat(), "local": n.astimezone(LOCAL_TZ).isoformat()}


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def log_event(event: dict):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    event = {"at": now_iso(), **event}
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


# ---------------------------------------------------------------- case -----

class Case:
    """A single outreach case. The verbatim fields are immutable after load:
    if a case file's stored hash does not match its verbatim text, load fails."""

    def __init__(self, data: dict, path: Path):
        self.data = data
        self.path = path
        v = data["verbatim"]
        expect = sha256_text(v["reason_for_contact"] + "\n---\n" + v["requested_action"])
        if data.get("verbatim_sha256") and data["verbatim_sha256"] != expect:
            raise ValueError(
                "VERBATIM INTEGRITY FAILURE: stored hash does not match the "
                "verbatim reason/requested_action in the case file. The ask "
                "must never change silently. Fix the case file or re-create it."
            )
        self.verbatim_hash = expect

    @classmethod
    def load(cls, path: str) -> "Case":
        p = Path(path)
        return cls(json.loads(p.read_text(encoding="utf-8")), p)

    @property
    def case_id(self):
        return self.data["case_id"]

    @property
    def reason(self):
        return self.data["verbatim"]["reason_for_contact"]

    @property
    def ask(self):
        return self.data["verbatim"]["requested_action"]


# ------------------------------------------------------- reply parsing -----

_REFERRAL_PATTERNS = [
    r"contact\s+([A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){0,3})\s+at\s+([\w.+-]+@[\w-]+\.[\w.]+)",
    r"direct\s+(?:your\s+)?(?:request|inquiry|case)\s+to\s+([A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){0,3})\s*[,(]?\s*([\w.+-]+@[\w-]+\.[\w.]+)",
    r"(?:your\s+)?(?:case|reference|ticket)\s*(?:number|no\.?|id)?\s*(?:is\s*:|:|is)\s*([A-Z0-9][A-Z0-9\-]{4,})",
    r"reach\s+(?:us|me)\s+at\s+([\w.+-]+@[\w-]+\.[\w.]+)",
]


def parse_reply(reply_text: str) -> dict:
    """Parse a reply for a named human, a referral address, or a case number.
    Carried over and extended from the original EmailCascade.parse_auto_reply."""
    found = {"named_human": None, "referral_email": None, "case_number": None}
    for pat in _REFERRAL_PATTERNS:
        m = re.search(pat, reply_text, re.IGNORECASE)
        if not m:
            continue
        groups = m.groups()
        if len(groups) == 2 and "@" in groups[1]:
            found["named_human"] = found["named_human"] or groups[0].strip()
            found["referral_email"] = found["referral_email"] or groups[1].strip().rstrip(".")
        elif len(groups) == 1 and "@" in groups[0]:
            found["referral_email"] = found["referral_email"] or groups[0].strip().rstrip(".")
        elif len(groups) == 1:
            found["case_number"] = found["case_number"] or groups[0].strip()
    found["is_substantive"] = bool(
        found["named_human"] or found["referral_email"] or found["case_number"]
        or len(reply_text.strip()) > 200
    )
    return found


# ------------------------------------------------------------ drafting -----

LEVEL_META = {
    0: ("DIRECTIONS_FIRST", "Do the target's published directions; log them. No draft."),
    1: ("INITIAL_EMAIL", "Initial email to the directed contact."),
    2: ("FOLLOWUP_1H", "1-hour no-reply follow-up, same thread."),
    3: ("ESCALATE_CC_2H", "2-hour escalation, next level CC'd, log attached."),
    4: ("MULTICHANNEL_3H", "3-hour: fax copy prepared + email notice."),
    5: ("LEGAL_PAPER_4H", "4-hour: certified mail to legal office prepared + email notice."),
    6: ("HOURLY_CONTINUED", "Hourly continued pressure, approach rotates, ask unchanged."),
}


def recipients_for_level(case: Case, level: int) -> dict:
    """Resolve To/CC for a level from the case's verified chain.
    Raises if any recipient used at this level is still TO_VERIFY."""
    chain = case.data["target"]["chain"]
    by_level = {c["chain_level"]: c for c in chain}

    def entry(n):
        e = by_level.get(n)
        if not e:
            raise ValueError(f"Case chain has no level {n} entry.")
        return e

    if level in (1, 2):
        to, cc = [entry(1)], []
    elif level == 3:
        to, cc = [entry(1)], [entry(2)]
    elif level in (4, 5, 6):
        to = [entry(1)]
        cc = [e for e in (by_level.get(2), by_level.get(3)) if e]
    else:
        raise ValueError(f"No recipients for level {level} (level 0 sends nothing).")

    for e in to + cc:
        if e.get("verification") != "VERIFIED" or not e.get("email"):
            raise ValueError(
                f"Recipient '{e.get('role')}' is {e.get('verification', 'UNSET')} "
                "with no verified email. The engine will not build an approval "
                "packet for an unverified recipient. Verify it from the target's "
                "published directions first — the original engine invented "
                "addresses; this one does not."
            )
    fmt = lambda e: f"{e['role']} <{e['email']}>"
    return {"to": [fmt(e) for e in to], "cc": [fmt(e) for e in cc],
            "fax_number": (by_level.get(1) or {}).get("fax"),
            "mail_address": (by_level.get(3) or {}).get("mail_address")}


def build_draft(case: Case, level: int, prior_log_summary: str = "") -> dict:
    """Build the exact draft text for a level. Verbatim blocks are inserted
    untouched between markers; elaboration wraps around them."""
    if level == 0:
        return {"level": 0, "name": LEVEL_META[0][0], "draft": None,
                "note": LEVEL_META[0][1]}
    recips = recipients_for_level(case, level)
    name = IDENTITY["owner_name"]
    sig = IDENTITY["signature_block"]
    target = case.data["target"]["organization"]
    subject = f"[{case.case_id}] {case.data['subject_line']} — Level {level} ({LEVEL_META[level][0]})"

    opener = {
        1: f"I am writing to {target} {IDENTITY.get('opener_context', 'about my own accounts')}, following the directions you publish for account help.",
        2: f"I am following up on my email sent one hour ago (case {case.case_id}), which has not received a reply. I am keeping the same request, word for word, below.",
        3: f"I am escalating my request (case {case.case_id}) after two hours without a reply, and copying the next office in your chain. My request is unchanged, word for word, below.",
        4: f"I am writing again on case {case.case_id} after three hours without a reply. A fax copy of this same letter follows to your office for the paper trail. My request is unchanged, word for word, below.",
        5: f"I am writing again on case {case.case_id} after four hours without a reply. A certified-mail copy of this letter and the full contact log follows to your legal office for the paper trail. My request is unchanged, word for word, below.",
        6: f"I am continuing to follow up on case {case.case_id}. My request is unchanged, word for word, below. Please assign a named human and a case or reference number to this matter.",
    }[level]

    contact_line = IDENTITY.get("contact_line") or (
        f"Contact for reply: {IDENTITY['from_email']}"
        + (f" / Google Voice {IDENTITY['voice_phone_display']}" if IDENTITY.get("voice_phone_display") else "")
    )
    contact_note = IDENTITY.get("contact_note", "")

    body = f"""{opener}

--- REASON FOR CONTACT (verbatim, unedited) ---
{case.reason}
--- END VERBATIM ---

--- WHAT I AM ASKING FOR (verbatim, unedited) ---
{case.ask}
--- END VERBATIM ---

{contact_line}
{contact_note}

{('CONTACT LOG SO FAR:' + chr(10) + prior_log_summary) if prior_log_summary else ''}
{sig}
"""
    body = body.strip() + "\n"
    # Verbatim integrity check on the finished draft.
    if case.reason not in body or case.ask not in body:
        raise ValueError("VERBATIM CHECK FAILED: draft does not contain the verbatim blocks byte-for-byte.")
    return {
        "level": level,
        "name": LEVEL_META[level][0],
        "from": f"{name} <{IDENTITY['from_email']}>",
        "to": recips["to"],
        "cc": recips["cc"],
        "subject": subject,
        "body": body,
        "body_sha256": sha256_text(body),
        "verbatim_sha256": case.verbatim_hash,
        "status": "DRAFT_AWAITING_USER_APPROVAL",
        "fax_number": recips.get("fax_number"),
        "mail_address": recips.get("mail_address"),
    }


# ------------------------------------------------------------- channels ----

def dispatch_fax_real(to_fax: str, text: str, case_id: str) -> dict:
    """FaxBetter adapter (from fax_hardmail_dispatch_v2.py).
    Honest stub: without the user's paid key this returns skipped_no_key
    and NO confirmation number is created."""
    api_key = os.environ.get("FAXBETTER_API_KEY", "")
    if not api_key:
        return {"channel": "fax", "status": "skipped_no_key",
                "reason": "FAXBETTER_API_KEY not configured — paid account is the user's call",
                "confirmation_id": None}
    if not to_fax:
        return {"channel": "fax", "status": "error", "reason": "no verified fax number for target"}
    payload = urllib.parse.urlencode({
        "api_key": api_key, "to": to_fax,
        "from": IDENTITY.get("voice_phone", IDENTITY["owner_name"]),
        "subject": f"[{case_id}] Follow-up request — {IDENTITY['owner_name']}",
        "content": text[:65000],
    }).encode()
    try:
        req = urllib.request.Request("https://www.faxbetter.com/api/v2/faxes/send",
                                     data=payload, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        return {"channel": "fax", "status": "sent", "to": to_fax, "provider_result": result}
    except Exception as e:
        return {"channel": "fax", "status": "error", "to": to_fax, "error": str(e)}


def dispatch_mail_real(mail_address: dict, text: str, case_id: str) -> dict:
    """Lob adapter (from fax_hardmail_dispatch_v2.py).
    Honest stub: without the user's paid key this returns skipped_no_key
    and NO tracking number is created."""
    api_key = os.environ.get("LOB_API_KEY", "")
    if not api_key:
        return {"channel": "certified_mail", "status": "skipped_no_key",
                "reason": "LOB_API_KEY not configured — paid account is the user's call",
                "tracking_number": None}
    if not mail_address:
        return {"channel": "certified_mail", "status": "error", "reason": "no verified mail address for target"}
    html = "<html><body><pre style='font-family:Courier New;font-size:10px;white-space:pre-wrap;'>" + \
           text.replace("<", "&lt;").replace(">", "&gt;") + "</pre></body></html>"
    payload = json.dumps({
        "description": f"[{case_id}] Follow-up request",
        "to": mail_address,
        "from": {"name": IDENTITY["owner_name"], "address_line1": "ADDRESS_ON_FILE_WITH_USER",
                 "address_city": "", "address_state": "", "address_zip": "", "address_country": "US"},
        "file": html, "color": False, "double_sided": True,
        "address_placement": "top_first_page", "mail_type": "usps_certified",
    }).encode()
    creds = base64.b64encode(f"{api_key}:".encode()).decode()
    try:
        req = urllib.request.Request("https://api.lob.com/v1/letters", data=payload, method="POST",
                                     headers={"Authorization": f"Basic {creds}",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        return {"channel": "certified_mail", "status": "queued",
                "letter_id": result.get("id"), "provider_result": result}
    except Exception as e:
        return {"channel": "certified_mail", "status": "error", "error": str(e)}


# ------------------------------------------------------------- approval ----

def write_approval_packet(case: Case, draft: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{case.case_id}_L{draft['level']}_{draft['name']}"
    (out_dir / f"{stem}.txt").write_text(
        f"From: {draft['from']}\nTo: {', '.join(draft['to'])}\n"
        f"Cc: {', '.join(draft['cc'])}\nSubject: {draft['subject']}\n\n{draft['body']}",
        encoding="utf-8")
    packet = {
        "case_id": case.case_id, "level": draft["level"], "name": draft["name"],
        "status": draft["status"], "body_sha256": draft["body_sha256"],
        "verbatim_sha256": draft["verbatim_sha256"],
        "approval_rule": ENGINE_CFG["approval_rule"],
        "send_via": ENGINE_CFG.get("send_via", "Operator mail route, exact approved copy only"),
        "created": now_iso(),
    }
    p = out_dir / f"{stem}.packet.json"
    p.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    log_event({"event": "draft_built", "case_id": case.case_id,
               "level": draft["level"], "body_sha256": draft["body_sha256"]})
    return p


def escalation_due(case_data: dict, last_sent_at_iso: str, replies: list) -> dict:
    """Decide whether the 60-minute clock has fired."""
    if any(r.get("is_substantive") for r in replies):
        return {"due": False, "reason": "substantive reply received — clock stopped, re-aim at named human"}
    last = datetime.fromisoformat(last_sent_at_iso)
    due_at = last + timedelta(minutes=REPLY_WINDOW_MIN)
    return {"due": datetime.now(timezone.utc) >= due_at,
            "due_at_utc": due_at.isoformat(), "window_minutes": REPLY_WINDOW_MIN}


# ----------------------------------------------------------------- main ----

def main():
    ap = argparse.ArgumentParser(description="FU FOIA core — draft-only by default, sends nothing")
    ap.add_argument("--case", required=False, help="Path to case.json")
    ap.add_argument("--variant", default="personal", help="Settings selector (single-variant repos load repo-root settings.json)")
    ap.add_argument("--settings", required=False, help="Explicit settings.json path (overrides --variant)")
    ap.add_argument("--level", type=int, default=1, help="Escalation level 1-6 (0 = directions only)")
    ap.add_argument("--all-levels", action="store_true", help="Build drafts for every level the chain supports")
    ap.add_argument("--dry-run", action="store_true", default=True, help="Default: build drafts only")
    ap.add_argument("--parse-reply", required=False, help="Parse a reply text and print the routing result")
    ap.add_argument("--channel-check", action="store_true", help="Report honest fax/mail channel status")
    args = ap.parse_args()

    if args.parse_reply:
        print(json.dumps(parse_reply(args.parse_reply), indent=2))
        return
    if args.channel_check:
        print(json.dumps({
            "fax": dispatch_fax_real("", "", "CHECK"),
            "certified_mail": dispatch_mail_real({}, "", "CHECK"),
            "email": {"channel": "email", "status": "ready_as_drafts",
                      "from": IDENTITY["from_email"],
                      "send_route": "Gmail connector after exact-copy approval"},
        }, indent=2))
        return
    if not args.case:
        ap.error("--case is required unless --parse-reply / --channel-check")

    case = Case.load(args.case)
    out_dir = VARIANT_DIR / "drafts" / case.case_id
    levels = [1, 2, 3, 4, 5, 6] if args.all_levels else [args.level]
    built, blocked = [], []
    for lv in levels:
        try:
            draft = build_draft(case, lv)
            if draft.get("draft") is None and "body" not in draft:
                built.append({"level": lv, "note": draft["note"]})
                continue
            pkt = write_approval_packet(case, draft, out_dir)
            built.append({"level": lv, "name": draft["name"], "packet": str(pkt),
                          "body_sha256": draft["body_sha256"]})
        except ValueError as e:
            blocked.append({"level": lv, "blocked_reason": str(e)})
            log_event({"event": "draft_blocked", "case_id": case.case_id,
                       "level": lv, "reason": str(e)})
    print(json.dumps({"case_id": case.case_id, "mode": "DRY_RUN_NOTHING_SENT",
                      "built": built, "blocked": blocked}, indent=2))


if __name__ == "__main__":
    main()
