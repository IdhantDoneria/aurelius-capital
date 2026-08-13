# Mentisrex Capital — project rules

## HARD RULE: nothing mentioned in a prompt gets silently skipped

If a prompt asks for something to be built, it gets built. No quiet omissions,
no "left for later" without saying so.

The only allowed exception is genuine impossibility. If a requested item cannot
be built, you MUST:

1. **State it explicitly** — name the exact item skipped.
2. **Give the concrete reason** — why it is impossible *right now* (missing
   upstream data, absent dependency, external system not available, etc.).
3. **Name what would unblock it** — the specific change that makes it buildable.

"Impossible" means the data or dependency does not exist — NOT "large",
"tedious", or "YAGNI". Effort is not a valid skip reason. Fabricating a result
to appear complete is worse than an honest, documented skip.

Every skip must be recorded in the relevant `docs/*.md` under a **Known
limitations** / **Skipped** section, with the same three points.

## HARD RULE: commit every meaningful change immediately

After any meaningful change — new script/module, a reproduction or campaign run,
a report, a bug fix, a doc — `git commit` it before moving on. No batching a
session's worth of work into one uncommitted pile; uncommitted work is lost work.

"Meaningful" = anything you'd be unhappy to lose. Trivial scratch (a print
tweak reverted seconds later) does not need its own commit.

Commit message: conventional-commit type + one-line what/why. End with
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
