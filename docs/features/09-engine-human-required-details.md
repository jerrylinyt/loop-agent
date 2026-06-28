# Feature 09: Machine-Readable Human Required Details

## Type

Engine additive state. Avoid changing escalation policy.

## Goal

Store human intervention details in stable fields so dashboard can explain why the loop stopped and what the user should do.

## Problem

The dashboard can infer `human_required`, but the reason and suggested action are mostly log-derived. This makes UX inconsistent.

## Proposed State Fields

Add or update these fields when setting `human_required: true`:

```yaml
human_required: true
human_required_code: git_review_failed
human_required_reason: "Git Review Gate requested human review."
human_required_since: "2026-06-28 23:10:00"
suggested_human_action: "Review the diff and validation evidence, then resume."
```

For plan loop:

```yaml
plan_human_required: true
plan_human_required_code: plan_not_converging
plan_human_required_reason: "Plan did not converge after enhanced rounds."
plan_human_required_since: "2026-06-28 23:10:00"
plan_suggested_human_action: "Review PLAN.md and requirements, then rerun planning."
```

## Implementation Plan

1. Add helper functions to set and clear human-required details.
2. Replace direct writes of `human_required: true` with helper calls.
3. Preserve existing `human_required` field for compatibility.
4. Clear details on resume only when current behavior already clears `human_required`.
5. Update dashboard to prefer structured fields when available.

## Human Required Codes

Initial stable code set:

- `git_review_failed`
- `core_state_corrupt`
- `agent_human_conflict`
- `frozen_dependency_deadlock`
- `oscillation_hard_stop`
- `plan_not_converging`
- `tree_growth_stall`
- `unknown`

## Acceptance Criteria

- Every engine path that sets `human_required: true` also writes code, reason, timestamp, and suggested action.
- Existing dashboard still works if fields are absent.
- Resume behavior remains compatible.
- No change to escalation thresholds or loop policy.

## Tests

- Unit tests for helper functions.
- Tests for at least one execute-loop and one plan-loop human-required path.
- Dashboard manual check displays structured reason.

