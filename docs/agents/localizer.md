# Localizer — specification

## Purpose
Given a defect's problem statement and the target repository, return a short ranked list of `file:function` candidates that are likely to contain the bug, with a confidence score and a one-line evidence note for each.

## Milestone simplification — read this carefully
**No vector search, no embeddings, no reranker this week.** The retrieval strategy is grep + Claude file-ranker. The full hybrid + rerank stack is Phase 2.

## Inputs (from `DefectState`)
- `problem_statement: str`
- `repo: str` — the local path to the checked-out repo at `base_commit`

## Outputs (merged into state)
- `candidates: list[LocalizationCandidate]` — top 5
- `confidence: float` — the score of the top candidate
- `deep_search_done: bool` — see "Conditional deep search" below

## Algorithm

1. **Extract search terms.** Send the problem statement to Claude with a prompt asking for 3–6 short, distinctive search terms (identifiers, error message fragments, function names mentioned in the issue). Schema: JSON list of strings.

2. **Grep the repo.** For each term, run `git grep -n -i <term>` inside `repo`. Collect matches as `(file_path, line_number, line_text)`.

3. **Bucket matches by file.** Aggregate to a per-file score = number of distinct terms that matched in that file. Take the top 15 files.

4. **Attach functions via `ast`.** For each top file, parse the file with `ast`, walk `FunctionDef`/`AsyncFunctionDef`/`ClassDef`, and for each matching line number record the enclosing function name and line range.

5. **Ask Claude to rank.** Send Claude the problem statement and the top 15 file snippets (only the matched lines + a few lines of context, not whole files). Ask for a ranked top 5 with `score` (0.0–1.0) and one-line `evidence` per candidate. Schema: JSON.

6. **Build the candidate list.** Convert Claude's response to `LocalizationCandidate` entries, attaching the function name and line range from step 4 where available.

7. **Confidence.** `state["confidence"] = candidates[0]["score"]`.

## Conditional deep search
If `confidence < 0.5` and `deep_search_done == False`:

- Re-run with a wider net: ask Claude for 8–10 additional search terms (synonyms, related concepts), repeat steps 2–6, merge candidates de-duped by `(file_path, function)` keeping the higher score.
- Set `deep_search_done = True` so we don't loop forever.

(This is the conditional edge on the Localizer; the graph routes back into the same node once. Implement as an internal retry inside the node, not a separate graph edge — keeps the milestone graph simple.)

## Prompt sketches

**Extract-terms prompt:**
```
You are reading a software bug report. Output a JSON list of 3-6 short, distinctive
search terms that are most likely to appear verbatim in the buggy code. Prefer
identifiers, function names, error message fragments. Avoid common words.

Bug report:
{problem_statement}

Output JSON only.
```

**Rank-candidates prompt:**
```
You are localizing a bug to a file:function in a Python repository.

Bug report:
{problem_statement}

Candidate files with the lines that matched search terms:
{rendered_snippets}

Return a JSON list of up to 5 candidates, each with:
- file_path, function (or null), line_start, line_end, score (0-1), evidence (one sentence).

Sort by score descending. Output JSON only.
```

## What this node MUST NOT do
- Touch any vector store, embedding model, or reranker. Phase 2.
- Read whole files into the prompt — only matched lines + minimal context. Token budget matters.
- Loop more than once on deep search.
- Modify any file in the target repo (`repo`).

## Manual verification (Day 2)
After implementing, run it against one SWE-bench instance and check by eye that the true buggy file is in the top 5. If it isn't, do not chase localization quality this week — note it and move on. The Patch-writer will still get its chance.
