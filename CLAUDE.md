# Aurelius Capital — project rules

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
