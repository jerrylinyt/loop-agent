# Loop Engineering UX and Engine Feature Plans

This folder contains implementation-ready feature plans for improving Loop Engineering.

The plans are split by feature so separate agents can implement them independently. Each document states whether the feature is dashboard-only, docs-only, or requires engine changes.

## Remaining Features (Not Yet Implemented)

1. `09-engine-human-required-details.md` - structured human-required details
2. `10-engine-preflight-json.md` - engine-owned structured preflight
3. `16-engine-state-transition-guard.md` - revisioned guarded state writes
4. `11-engine-run-sessions.md` - structured run sessions in `rounds.jsonl`
5. `13-engine-artifact-index.md` - round artifact metadata in `rounds.jsonl`
6. `07-docs-quickstart-troubleshooting.md` - quick start and troubleshooting docs

## Priority Order for Control-Error Reduction

If the goal is to reduce agent control mistakes, implement in this order:

1. Feature 09
2. Feature 10
3. Feature 16
4. Feature 11
5. Feature 13

Rationale:

- Feature 09 makes stop reasons and next actions explicit.
- Feature 10 removes split authority for startup readiness.
- Feature 16 hardens state transitions and stale-writer conflicts.
- Feature 11 makes run ownership and terminal outcomes attributable.
- Feature 13 makes recent changes and validation evidence reviewable.

## Already Implemented (Removed)

The following feature plans were completed and have been removed from this directory:

- ~~01-dashboard-next-action~~ - Next Action Panel
- ~~02-actionable-preflight~~ - Actionable Preflight Results
- ~~03-dashboard-log-viewer~~ - Log Viewer Upgrade
- ~~04-dashboard-diff-review~~ - Diff Review Upgrade
- ~~05-human-required-inbox~~ - Human Required Inbox
- ~~06-onboarding-wizard~~ - Onboarding / Config Wizard
- ~~08-engine-structured-events~~ - Structured Event Log (merged into `rounds.jsonl` typed records)
- ~~12-engine-cooperative-stop~~ - Cooperative Stop
- ~~14-state-cli-and-json-review-gate~~ - State CLI + Review Gate JSON (superseded by Feature 15)
- ~~15-machine-readable-state-store~~ - `state.json` store

## Scope Rules

- Dashboard-only features must not change `engine/` or loop behavior.
- Engine features should add observable state and machine-readable outputs first; avoid changing planning or execution strategy unless explicitly required.
- Every feature should include tests or a clear manual verification checklist before being marked done.
- Existing user work in the repository must not be reverted.
