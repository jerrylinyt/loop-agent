# Loop Engineering UX and Engine Feature Plans

This folder contains implementation-ready feature plans for improving Loop Engineering.

The plans are split by feature so separate agents can implement them independently. Each document states whether the feature is dashboard-only, docs-only, or requires engine changes.

## Suggested Implementation Order

1. `01-dashboard-next-action.md`
2. `02-actionable-preflight.md`
3. `03-dashboard-log-viewer.md`
4. `04-dashboard-diff-review.md`
5. `05-human-required-inbox.md`
6. `06-onboarding-wizard.md`
7. `07-docs-quickstart-troubleshooting.md`
8. `08-engine-structured-events.md`
9. `09-engine-human-required-details.md`
10. `10-engine-preflight-json.md`
11. `11-engine-run-sessions.md`
12. `12-engine-cooperative-stop.md`
13. `13-engine-artifact-index.md`
14. `14-state-cli-and-json-review-gate.md`
15. `15-machine-readable-state-store.md`

## Scope Rules

- Dashboard-only features must not change `engine/` or loop behavior.
- Engine features should add observable state and machine-readable outputs first; avoid changing planning or execution strategy unless explicitly required.
- Every feature should include tests or a clear manual verification checklist before being marked done.
- Existing user work in the repository must not be reverted.

