# Feature 13: Engine Artifact Index

## Type

Engine additive observability.

## Goal

Record what changed and what evidence exists for each round so human review is faster.

## Problem

Human reviewers need to know which files changed, which commands ran, and what validation evidence exists. Today this information is split across logs, git diff, and agent-written text.

## Proposed Artifact

Append JSON lines to:

```text
<repo>/.loop/<ws>/.loop_state/artifacts.jsonl
```

Example:

```json
{
  "ts": "2026-06-28 23:12:00",
  "run_id": "default:20260628-230100",
  "round": 3,
  "phase": "2",
  "changed_files": ["src/app.py", "tests/test_app.py"],
  "git_head_before": "abc123",
  "git_head_after": "def456",
  "commit": "def456",
  "validation_summary": "pytest passed",
  "evidence_files": []
}
```

## Implementation Plan

1. Capture git HEAD before and after each agent round.
2. Use git diff/name-only to record changed files.
3. Store commit SHA when autocommit succeeds.
4. Optionally parse validation evidence from structured agent output later.
5. Keep artifact writes best-effort.

## Acceptance Criteria

- Each completed round can produce an artifact record.
- Records include changed files and commit/head data when available.
- Missing git data does not crash the loop.
- Dashboard can later show "what changed this round".

## Tests

- Unit test artifact append helper.
- Integration test with a mock repo and one changed file.
- Verify no artifact file is committed to project git history.

