# Architecture

## One core, variants are settings

`core/outreach_engine.py` never hardcodes an identity. At startup it loads
`variants/<name>/settings.json`:

```json
{ "variant": "public", "identity": { ... }, "engine": { ... } }
```

- `identity` — From address, signature, contact lines, callback number (or the
  deliberate absence of one, in the anonymous variant).
- `engine` — escalation ladder, reply window (60 minutes), channel providers,
  approval rule.

Adding a variant = adding a folder with a `settings.json` and `cases/`.
No code fork.

## The verbatim lock

Every case file carries `verbatim.reason_for_contact` and
`verbatim.requested_action` plus `verbatim_sha256` =
SHA-256(reason + "\n---\n" + action). Loading a case recomputes the hash;
a mismatch fails the load. Every built draft is checked to contain both
blocks byte-for-byte before an approval packet is written. Escalation
levels change opener text, recipients, CCs, and channels — the verbatim
blocks are inserted untouched at every level.

## The approval gate

A draft's status is `DRAFT_AWAITING_USER_APPROVAL` and its packet records
the SHA-256 of the exact body. Approval covers that hash only. Editing a
draft after approval produces a different hash and needs a new approval.
The engine itself has no send path for email: it emits drafts + packets,
and the operator sends the approved copy through their mail route (through the
operator's own mail route — see the edition's settings).

## Honest channels

- **Email** — ready as drafts; send is an operator action after approval.
- **Fax (FaxBetter)** — real API adapter. Without `FAXBETTER_API_KEY` in the
  environment it returns `{"status": "skipped_no_key", "confirmation_id": null}`.
- **Certified mail (Lob)** — real API adapter. Without `LOB_API_KEY` it
  returns `{"status": "skipped_no_key", "tracking_number": null}`.

A confirmation or tracking value exists in a log only when a provider
returned it. Recipients must carry `verification: VERIFIED` in the case's
chain (verified from the target's published directions) or the engine
refuses to build that level's packet.

## Reply handling

`parse_reply()` extracts a named human, a referral email, and a case /
reference number from a reply. A substantive reply stops the escalation
clock; the next 60-minute window is aimed at the named human.

## Relationship to OsintNeoAi

This is a satellite app repo, like TaxFunded and the Non-Profiteers Index:
independent code and releases, but built to plug into the OsintNeoAi user
workspace — the `osintneoai` variant is the workspace's outreach surface,
and cases/logs produced here are shaped to be filed back into OsintNeoAi's
evidence and task systems.
