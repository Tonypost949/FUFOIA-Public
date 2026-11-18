# How the two FU FOIA repos stay in sync

Two repos, one system. The core is shared **both ways**; what each edition
*is* never crosses over.

- **FUFOIA-Public** — the signed edition (Neo + the owner work here).
- **FUFOIA-Anonymous** — the OsintNeoAi workspace edition, maintained
  **only by agy + IntelliJ IDEA** (owner rule, same as the website).

## What syncs: core mechanics, in either direction

The core is a single file: `core/outreach_engine.py`. Its version is in
`CORE_VERSION` in both repos (currently `fufoia-core 1.0.0` in both).

A core mechanic is the machinery both editions need: the escalation ladder,
the verbatim lock, the reply parser, the channel adapters, the approval gate.
If a better mechanic is built on **either** side — say IntelliJ improves the
ladder on the Anonymous side — the other side takes it too:

1. Whoever improves the core bumps `CORE_VERSION` in their repo and commits
   with the version in the message.
2. The other side pulls the new core file over and bumps their
   `CORE_VERSION` to match — deliberately, by that repo's own maintainers
   (agy/IntelliJ for Anonymous; Neo/the owner for Public). Never automatic,
   and nobody pushes into the other repo.

## What NEVER syncs: what each edition is

- **Identity and settings.** Public signs as a named person; Anonymous signs
  as the unit. Settings files never move between repos.
- **Cases.** Each edition's cases are its own.
- **Edition-only behavior.** If a behavior belongs to one edition only, it
  lives in that edition's **settings** as data — never as a special case in
  the core. That is the separation mechanism: because everything
  edition-specific is settings, pulling the core across can improve the
  machinery without ever dragging the other edition's purpose with it.

## Why not automatic sync

The owner's rule is that the website side is touched only by agy + IntelliJ.
An automatic mirror would be another agent's write into their territory.
The version file is the communication: each repo can always see which core
the other is running, and the pull is a deliberate act by the maintainers.

*(This page lives in FUFOIA-Public, where core work is coordinated. The
Anonymous repo carries its own copy; its maintainers adopt updates to this
page when they pull a core version, per the same rule.)*
