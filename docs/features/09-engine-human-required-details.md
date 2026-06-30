# Feature 09: Structured Human-Required Details

## Type

Engine additive state. Avoid changing escalation policy.

## Goal

Store human intervention details in stable fields so engine, CLI, and dashboard can explain why the loop stopped and what the user should do next.

## Problem

`human_required` exists today, but the surrounding detail is still ad hoc. Some paths only set a terse reason string, some rely on log text, and dashboard code still has to infer meaning from mixed fields. That weakens stop semantics and makes resume behavior harder to trust.

## Proposed State Fields

Add or update these fields when setting `human_required: true`:

```yaml
human_required: true
human_required_code: git_review_failed
human_required_reason: "Git Review Gate requested human review."
human_required_since: "2026-06-28 23:10:00"
suggested_human_action: "Review the diff and validation evidence, then resume."
human_required_source: "execute_loop"
human_required_run_id: "repo:default:1719587400"
```

For plan loop:

```yaml
plan_human_required: true
plan_human_required_code: plan_not_converging
plan_human_required_reason: "Plan did not converge after enhanced rounds."
plan_human_required_since: "2026-06-28 23:10:00"
plan_suggested_human_action: "Review PLAN.md and requirements, then rerun planning."
plan_human_required_source: "plan_loop"
plan_human_required_run_id: "repo:default:1719587400"
```

Notes:

- Keep legacy fields `human_required_reason` and `human_required_msg` for compatibility during migration.
- `*_code` is the stable machine key; `*_reason` remains human-readable text.
- `*_run_id` is required so dashboard resume and later state guards can verify who set the stop.

## Implementation Plan

1. Expand helper functions in `engine/state.py` to set and clear the full structured payload for both execute and plan paths.
2. Replace direct `human_required` and `plan_human_required` writes with helpers everywhere in engine entrypoints and hard-stop paths.
3. Preserve legacy fields for compatibility, but make dashboard and future CLI output prefer the structured fields.
4. When clearing `human_required`, clear only the matching namespace and preserve unrelated plan/execute stop details.
5. Thread `run_id` into helper calls so every stop can be traced back to the run that created it.
6. Add a small stable code registry in docs or code comments so new stop reasons do not invent near-duplicate labels.

## Human Required Codes

Initial stable code set:

- `git_review_failed`
- `broken_control_file`
- `agent_requested`
- `frozen_dependency_deadlock`
- `stuck_level_2_hard_stop`
- `max_rounds_reached`
- `plan_not_converging`
- `tree_growth_stalled`
- `tree_structure_error`
- `max_leaf_reflow_exceeded`
- `unknown`

The code set should match existing engine stop paths first, then be extended deliberately.

## Acceptance Criteria

- Every engine path that sets execute or plan `human_required` also writes code, reason, timestamp, suggested action, source, and `run_id`.
- Existing dashboard still works if fields are absent, but prefers the new fields when present.
- Resume behavior remains compatible and does not accidentally clear the wrong stop namespace.
- No change to escalation thresholds or loop policy.
- New fields are documented as additive and safe for partial rollout.

## Tests

- Unit tests for helper functions, including clear behavior and `run_id` propagation.
- Tests for at least one execute-loop and one plan-loop human-required path.
- Dashboard manual check displays structured reason and suggested action.
