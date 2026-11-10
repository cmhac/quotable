# Project Rules

- Enforce global security policies from ~/.kiro/steering/security.md
- Do not bypass hooks — all tool operations are gated by security checks
- All hooks delegate to the global security script; do not duplicate security logic in the repo
- If a hook blocks an action, do not retry or work around it
