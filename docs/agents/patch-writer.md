# Patch-writer — specification

## Purpose
Given a defect's problem statement, the localized candidate(s), and optional critic feedback from a previous failed attempt, draft a unified diff that attempts to fix the bug. Scope the change to the localized region.

## Inputs (from `DefectState`)
- `problem_statement: str`
- `candidates: list[LocalizationCandidate]` (top candidate is the primary target)
- `critic_feedback: Optional[str]` (present from the second attempt onward)
- `repo: str` (path to the checked-out repo)

## Outputs (merged into state)
- `diff: str` — a valid unified diff applicable from `repo` root
- `patch_attempts: int` (incremented by 1)

## Algorithm

1. **Read the candidate file(s).** Read the top candidate's full file from disk (small Python files; if file is > 800 lines, read only the +/- 100 lines around the candidate line range and note it in the prompt).

2. **Build the prompt.** Provide Claude with:
   - The problem statement.
   - The top candidate's `file_path`, `function`, `line_start`/`line_end`, and `evidence`.
   - The current file content (full or windowed).
   - If `critic_feedback` is present, include it under a clearly labeled "Previous attempt failed because:" section.
   - An instruction to output **only a unified diff** in the standard `--- a/... +++ b/...` format, with no commentary.

3. **Validate the diff.**
   - Parse with `unidiff.PatchSet`.
   - Reject if it modifies more than 3 files (keep scope tight for the milestone).
   - Reject if it modifies any file outside `repo`.
   - Reject if it modifies test files (we want fixes in source, not test patches that game the harness).
   - On reject, ask Claude once to retry with the validation error as feedback. If still invalid, write the invalid diff to the artefact directory and let the Test-runner record a failure.

4. **Write the diff to the run artefact directory** as `patch_attempts/<n>.diff`.

## Prompt sketch

```
You are fixing a bug in a Python repository. Output ONLY a unified diff that applies
from the repository root. No explanation, no markdown fences, just the diff.

Bug report:
{problem_statement}

Most likely buggy location:
- File: {file_path}
- Function: {function}
- Lines: {line_start}-{line_end}
- Why: {evidence}

Current content of {file_path}:
```
{file_content}
```

{previous_failure_section_if_any}

Constraints:
- Modify only source files, never test files.
- Keep the change as small as possible.
- Output a single unified diff. Start with `diff --git` or `--- a/`.
```

## What this node MUST NOT do
- Modify test files in the target repo (we want real fixes, not eval gaming).
- Generate explanatory text alongside the diff — only the diff.
- Open a PR or commit anything (PR-opener is Phase 2).
- Retry indefinitely on invalid diffs — one internal retry, then accept the failure and let the Test-runner record it.

## Notes for the retry path
When called the second or third time (via the Critic → Patch-writer edge), the `critic_feedback` will be in state. Place it prominently in the prompt — it is the most useful signal Claude has. Do not silently ignore it.
