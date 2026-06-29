# Loop Engineering UX and Engine Feature Plans

This folder contains implementation-ready feature plans for improving Loop Engineering.

The plans are split by feature so separate agents can implement them independently. Each document states whether the feature is dashboard-only, docs-only, or requires engine changes.

## Remaining Features (Not Yet Implemented)

1. `07-docs-quickstart-troubleshooting.md` — Quick Start 與 Troubleshooting 文件
2. `09-engine-human-required-details.md` — 結構化 human_required 詳情欄位
3. `10-engine-preflight-json.md` — 引擎 CLI `--preflight --json` 輸出
4. `11-engine-run-sessions.md` — Run Session manifest 歷史紀錄
5. `13-engine-artifact-index.md` — 每輪 changed files / evidence artifact 紀錄

## Already Implemented (Removed)

The following feature plans were completed and have been removed from this directory:

- ~~01-dashboard-next-action~~ — Next Action Panel ✅
- ~~02-actionable-preflight~~ — Actionable Preflight Results ✅
- ~~03-dashboard-log-viewer~~ — Log Viewer Upgrade ✅
- ~~04-dashboard-diff-review~~ — Diff Review Upgrade ✅
- ~~05-human-required-inbox~~ — Human Required Inbox ✅
- ~~06-onboarding-wizard~~ — Onboarding / Config Wizard ✅
- ~~08-engine-structured-events~~ — Structured Event Log (merged into rounds.jsonl typed records) ✅
- ~~12-engine-cooperative-stop~~ — Cooperative Stop ✅
- ~~14-state-cli-and-json-review-gate~~ — State CLI + Review Gate JSON (superseded by Feature 15) ✅
- ~~15-machine-readable-state-store~~ — state.json Store ✅

## Scope Rules

- Dashboard-only features must not change `engine/` or loop behavior.
- Engine features should add observable state and machine-readable outputs first; avoid changing planning or execution strategy unless explicitly required.
- Every feature should include tests or a clear manual verification checklist before being marked done.
- Existing user work in the repository must not be reverted.
