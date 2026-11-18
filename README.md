# FU FOIA — Public

**FU FOIA** is the Follow-Up FOIA system: it takes a reason for contact, keeps it **verbatim** (hash-locked), and follows up on a **60-minute escalation ladder** across email, internet fax, and certified hard mail — changing only the approach, never the ask — until a named human answers.

This repo is the **Public** edition — the signed one. It was built first for Anthony DiMarcello's own use, and it is equally the form an investigator uses when they choose **not** to be anonymous: the sender acts under their own name.

- Sends **signed, as himself**: Anthony Michael DiMarcello III, from **amd949609@gmail.com** (his main email and the backup recovery email for everything he does), Google Voice **(949) 424-5769** on every message.
- Nothing is sent without him approving the exact copy (approval is bound to the hash of the approved text).
- Standing rule (owner, 2026-11-18): every account/email access problem goes through this engine.

The other edition is [FUFOIA-Anonymous](https://github.com/Tonypost949/FUFOIA-Anonymous) — the anonymous OsintNeoAi investigator / user-workspace edition. The two repos share one core by versioned copy (see `SYNC.md`); neither writes into the other.

## Cases

- `cases/google-accounts-001.json` — **ON HOLD, NOT ARMED.** amd949609 itself is fine and is only the sending/recovery account (owner correction, 2026-11-18). The accounts at issue are anthonymichaeldimarcello@gmail.com and disoledesign@gmail.com. Verbatim wording fields are empty — the wording is the owner's to give, in his own words.
- `cases/template_case.json` — blank case for any new problem.

## Run it

```
python3 core/outreach_engine.py --case cases/google-accounts-001.json --all-levels --dry-run
python3 core/outreach_engine.py --channel-check
python3 core/outreach_engine.py --parse-reply "<reply text>"
```

Dry-run is the default and the engine sends nothing itself; email goes out through the Gmail connector only after exact-copy approval. Fax (FaxBetter) and certified mail (Lob) honestly return `skipped_no_key` until the owner wires his own paid accounts — no confirmation or tracking number is ever fabricated, and no recipient address is ever invented (unverified recipients block the draft).

## Layout

- `core/outreach_engine.py` — the FU FOIA core (see `CORE_VERSION`)
- `settings.json` — the Public settings (identity + ladder + channels)
- `cases/`, `tests/`, `ARCHITECTURE.md`, `SYNC.md`

Lineage: descends from the Omni-Channel Legal Service & Outreach Engine and the Anonymous FOIA Dispatch Engine (Sep 5, 2026) — the originals are preserved in the Anonymous edition's `original/` folder with their graded defects on the record.
