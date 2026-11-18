# How the two FU FOIA repos stay in sync

Two repos, one system, one-directional flow:

- **FUFOIA-Public** — where the shared core is developed (Neo + the owner).
- **FUFOIA-Anonymous** — the OsintNeoAi workspace edition, maintained **only by agy + IntelliJ IDEA** (owner rule, same as the website).

## The mechanism

1. The core is a single file: `core/outreach_engine.py`. Its version is in
   `CORE_VERSION` in both repos (currently `fufoia-core 1.0.0` in both).
2. When the core changes in FUFOIA-Public, `CORE_VERSION` bumps there and
   the change is committed with the version in the message.
3. FUFOIA-Anonymous updates **only when agy/IntelliJ deliberately pull** the
   new core file over and bump their `CORE_VERSION` to match. Nothing is
   pushed into the Anonymous repo by the Personal side, automatically or
   otherwise.
4. Settings and cases **never** sync. They are the editions' whole point of
   separation: Public settings carry the sender's own identity; Anonymous
   settings carry the unit identity; neither repo's cases move.

## Why not automatic sync

The owner's rule is that the website side is touched only by agy + IntelliJ.
An automatic mirror would be another agent's write into their territory.
The version file is the communication: each repo can always see which core
the other is running, and the pull is a deliberate act by the maintainers.
