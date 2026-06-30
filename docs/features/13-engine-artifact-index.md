# Feature 13: Round Artifact Metadata

## Type

Engine additive observability and review support.

## Goal

Record what changed and what evidence exists for each round so human review, stop analysis, and resume decisions are faster.

## Problem

Human reviewers need to know which files changed, which commands ran, and what validation evidence exists. Today this information is split across logs, git diff, and agent-written text. When a run stops or oscillates, there is no compact machine-readable answer to "what changed in the last few rounds".

## Proposed Record

Do not create a separate `artifacts.jsonl`. Append artifact-bearing typed records to `.loop_state/rounds.jsonl`.

Example:

```json
{
  "type": "round_artifact",
  "ts": "2026-06-28 23:12:00",
  "run_id": "default:20260628-230100",
  "round": 3,
  "loop_type": "execute",
  "phase": "2",
  "changed_files": ["src/app.py", "tests/test_app.py"],
  "git_head_before": "abc123",
  "git_head_after": "def456",
  "commit": "def456",
  "validation_summary": "pytest passed",
  "validation_status": "passed",
  "evidence_files": []
}
```

## Implementation Plan

1. Capture git HEAD before and after each agent round.
2. Use git diff/name-only to record changed files.
3. Store commit SHA when autocommit succeeds.
4. Attach validation summary and validation status when available from existing round flow.
5. Keep artifact writes best-effort and append-only.
6. Expose a small reader helper so dashboard can fetch the latest artifact-bearing records without re-parsing unrelated logs.

## Acceptance Criteria

- Each completed round can produce an artifact-bearing record.
- Records include changed files and commit/head data when available.
- Missing git data does not crash the loop.
- Dashboard can later show "what changed this round" and "what evidence exists" from structured records.
- The latest changed files for a stopped run are machine-readable without scraping log text.

## Tests

- Unit test artifact append helper.
- Integration test with a mock repo and one changed file.
- Verify no new standalone artifact file is committed to project git history.
