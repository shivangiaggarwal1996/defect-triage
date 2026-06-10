"""Localizer node: grep + LLM file-ranker to find the buggy file.

Read docs/agents/localizer.md before changing this. NOT vector search for the
milestone — the retrieval strategy is deliberately just ``git grep`` plus an LLM
ranker.

THE ALGORITHM (per the spec)
----------------------------
  1. Ask the model for a few distinctive search terms from the bug report.
  2. ``git grep`` each term across the repo's Python files.
  3. Bucket matches by file; score each file by how many distinct terms it matched;
     keep the top 15 files.
  4. Use ``ast`` to find which function/class encloses each matched line.
  5. Ask the model to rank the top files (showing only matched lines + a little
     context — never whole files) into a top-5 with a score and one-line evidence.
  6. Build LocalizationCandidate entries, attaching the function/line range from (4).
  7. Confidence = the top candidate's score.

CONDITIONAL DEEP SEARCH
-----------------------
If confidence < 0.5 and we have not already retried, widen the net once: ask for
more terms, repeat 2–6, and merge the results (de-duped by file+function, keeping the
higher score). Implemented as an internal retry so the graph stays simple.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from ..llm import complete
from ..state import DefectState, LocalizationCandidate

# Tuning knobs (kept small to respect the token budget — see the spec's pitfalls).
TOP_FILES = 15            # how many files to hand the ranker
MAX_LINES_PER_FILE = 6    # matched lines shown per file in the rank prompt
CONTEXT = 1               # lines of context shown on each side of a matched line
DEEP_SEARCH_THRESHOLD = 0.5


# --------------------------------------------------------------------------------
# JSON helpers — the model sometimes wraps JSON in ```fences```; strip them.
# --------------------------------------------------------------------------------

def _parse_json(text: str):
    """Parse JSON from a model response, tolerating Markdown code fences."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        # Fall back to grabbing the first [...] or {...} block in the text.
        match = re.search(r"(\[.*\]|\{.*\})", stripped, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise


# --------------------------------------------------------------------------------
# Step 1 — extract search terms (LLM call)
# --------------------------------------------------------------------------------

def _extract_terms(problem_statement: str, instance_id: str, *, wide: bool = False) -> list[str]:
    """Ask the model for distinctive grep terms from the bug report.

    Args:
        wide: if True, request 8–10 broader/synonym terms (for the deep-search retry)
            instead of the initial 3–6 precise ones.
    """
    count = "8-10 additional, broader" if wide else "3-6"
    prompt = (
        "You are reading a software bug report. Output a JSON list of "
        f"{count} short, distinctive search terms that are most likely to appear "
        "verbatim in the buggy code. Prefer identifiers, function names, and error "
        "message fragments. Avoid common English words.\n\n"
        f"Bug report:\n{problem_statement}\n\nOutput JSON only."
    )
    raw = complete(
        [{"role": "user", "content": prompt}],
        node="extract_terms",
        instance_id=instance_id,
    )
    terms = _parse_json(raw)
    # Keep only non-trivial string terms (drop empties / single characters).
    return [t for t in terms if isinstance(t, str) and len(t.strip()) > 1]


# --------------------------------------------------------------------------------
# Step 2 — grep the repo
# --------------------------------------------------------------------------------

def _grep(repo: str, terms: list[str]) -> list[tuple[str, int, str, str]]:
    """Run ``git grep`` for each term inside ``repo`` (Python files only).

    Returns a flat list of ``(file_path, line_number, line_text, term)`` matches.
    """
    matches: list[tuple[str, int, str, str]] = []
    for term in terms:
        # -n line numbers, -i case-insensitive, -F fixed-string (term may contain
        # regex/punctuation), restricted to *.py. cwd MUST be the repo (git grep
        # only works inside the worktree — a common pitfall).
        result = subprocess.run(
            ["git", "grep", "-n", "-i", "-F", "-e", term, "--", "*.py"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        # git grep exits 0 when it finds matches, 1 when it finds none; anything
        # else is a real error we just skip for this term.
        if result.returncode not in (0, 1):
            continue
        for line in result.stdout.splitlines():
            parts = line.split(":", 2)  # "path:lineno:content"
            if len(parts) < 3:
                continue
            path, lineno, content = parts
            if lineno.isdigit():
                matches.append((path, int(lineno), content, term))
    return matches


# --------------------------------------------------------------------------------
# Step 3 — bucket matches by file, take the top N
# --------------------------------------------------------------------------------

def _top_files(matches: list[tuple[str, int, str, str]], limit: int = TOP_FILES) -> list[str]:
    """Rank files by how many *distinct* terms matched (ties broken by raw count)."""
    distinct_terms: dict[str, set[str]] = defaultdict(set)
    total_hits: dict[str, int] = defaultdict(int)
    for path, _lineno, _text, term in matches:
        distinct_terms[path].add(term.lower())
        total_hits[path] += 1
    ranked = sorted(
        distinct_terms,
        key=lambda p: (len(distinct_terms[p]), total_hits[p]),
        reverse=True,
    )
    return ranked[:limit]


# --------------------------------------------------------------------------------
# Step 4 — attach enclosing functions via ast
# --------------------------------------------------------------------------------

def _scopes(source: str) -> list[tuple[str, int, int]]:
    """Return ``(qualified_name, start_line, end_line)`` for every def/class.

    Names are qualified (e.g. "Flask.dispatch_request") by tracking class/function
    nesting. Returns an empty list if the file cannot be parsed.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    scopes: list[tuple[str, int, int]] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                end = getattr(child, "end_lineno", child.lineno)
                scopes.append((name, child.lineno, end))
                walk(child, name + ".")  # descend with the qualified prefix
            else:
                walk(child, prefix)

    walk(tree, "")
    return scopes


def _enclosing(scopes: list[tuple[str, int, int]], line: int) -> tuple[str, int, int] | None:
    """Return the innermost scope containing ``line`` (or None)."""
    best: tuple[str, int, int] | None = None
    for name, start, end in scopes:
        if start <= line <= end and (best is None or start > best[1]):
            best = (name, start, end)
    return best


# --------------------------------------------------------------------------------
# Step 5 — render snippets and ask the model to rank
# --------------------------------------------------------------------------------

def _render_snippets(
    repo: str,
    files: list[str],
    matches: list[tuple[str, int, str, str]],
) -> tuple[str, dict[str, dict]]:
    """Render compact per-file snippets for the rank prompt.

    Also returns ``file_info``: for each file, the enclosing function (and its line
    range) that contains the most matched lines — used in step 6 to enrich the
    model's candidates.

    Returns:
        ``(rendered_text, file_info)`` where ``file_info[path] = {function,
        line_start, line_end}``.
    """
    lines_by_file: dict[str, list[int]] = defaultdict(list)
    terms_by_file: dict[str, set[str]] = defaultdict(set)
    for path, lineno, _text, term in matches:
        lines_by_file[path].append(lineno)
        terms_by_file[path].add(term)

    blocks: list[str] = []
    file_info: dict[str, dict] = {}

    for path in files:
        source = ""
        try:
            source = (Path(repo) / path).read_text(errors="replace")
        except OSError:
            pass
        src_lines = source.splitlines()
        scopes = _scopes(source)

        # Unique matched line numbers, capped to keep the prompt small.
        matched = sorted(set(lines_by_file[path]))[:MAX_LINES_PER_FILE]

        # Pick the function enclosing the most matched lines -> file_info[path].
        func_hits: dict[tuple[str, int, int], int] = defaultdict(int)
        for ln in matched:
            scope = _enclosing(scopes, ln)
            if scope:
                func_hits[scope] += 1
        if func_hits:
            (fname, fstart, fend), _ = max(func_hits.items(), key=lambda kv: kv[1])
            file_info[path] = {"function": fname, "line_start": fstart, "line_end": fend}

        # Build the snippet: each matched line with a little context, marked with ">".
        header = f"### {path}  — matched terms: {', '.join(sorted(terms_by_file[path]))}"
        body: list[str] = []
        for ln in matched:
            scope = _enclosing(scopes, ln)
            if scope:
                body.append(f"  (in {scope[0]})")
            lo = max(1, ln - CONTEXT)
            hi = min(len(src_lines), ln + CONTEXT)
            for i in range(lo, hi + 1):
                marker = ">" if i == ln else " "
                text = src_lines[i - 1] if i - 1 < len(src_lines) else ""
                body.append(f"  {marker}{i:>5}| {text}")
        blocks.append(header + "\n" + "\n".join(body))

    return "\n\n".join(blocks), file_info


def _rank(problem_statement: str, rendered: str, instance_id: str) -> list[dict]:
    """Ask the model to rank the candidate files; returns its raw JSON list."""
    prompt = (
        "You are localizing a bug to a file:function in a Python repository.\n\n"
        f"Bug report:\n{problem_statement}\n\n"
        f"Candidate files with the lines that matched search terms:\n{rendered}\n\n"
        "Return a JSON list of up to 5 candidates, each with: file_path, function "
        "(or null), line_start, line_end, score (0-1), evidence (one sentence). "
        "Sort by score descending. Output JSON only."
    )
    raw = complete(
        [{"role": "user", "content": prompt}],
        node="rank_candidates",
        instance_id=instance_id,
    )
    parsed = _parse_json(raw)
    return parsed if isinstance(parsed, list) else []


# --------------------------------------------------------------------------------
# Step 6 — turn ranked results into LocalizationCandidate entries
# --------------------------------------------------------------------------------

def _build_candidates(ranked: list[dict], file_info: dict[str, dict]) -> list[LocalizationCandidate]:
    """Convert the model's ranked dicts into typed candidates, enriched via ast."""
    candidates: list[LocalizationCandidate] = []
    for item in ranked:
        path = item.get("file_path")
        if not path:
            continue
        info = file_info.get(path, {})
        candidate: LocalizationCandidate = {
            "file_path": path,
            # Prefer the model's own answer, fall back to the ast-derived info.
            "function": item.get("function") or info.get("function"),
            "line_start": item.get("line_start") or info.get("line_start"),
            "line_end": item.get("line_end") or info.get("line_end"),
            "score": float(item.get("score", 0.0)),
            "evidence": item.get("evidence", ""),
        }
        candidates.append(candidate)
    return candidates


def _merge(
    primary: list[LocalizationCandidate],
    extra: list[LocalizationCandidate],
) -> list[LocalizationCandidate]:
    """Merge two candidate lists, de-duped by (file_path, function), higher score wins."""
    best: dict[tuple[str, str | None], LocalizationCandidate] = {}
    for cand in [*primary, *extra]:
        key = (cand["file_path"], cand.get("function"))
        if key not in best or cand["score"] > best[key]["score"]:
            best[key] = cand
    return sorted(best.values(), key=lambda c: c["score"], reverse=True)


# --------------------------------------------------------------------------------
# A single localization pass (steps 2–6), reused by the deep-search retry.
# --------------------------------------------------------------------------------

def _pass(repo: str, problem_statement: str, terms: list[str], instance_id: str) -> list[LocalizationCandidate]:
    matches = _grep(repo, terms)
    if not matches:
        return []
    files = _top_files(matches)
    rendered, file_info = _render_snippets(repo, files, matches)
    ranked = _rank(problem_statement, rendered, instance_id)
    return _build_candidates(ranked, file_info)


# --------------------------------------------------------------------------------
# The graph node
# --------------------------------------------------------------------------------

def localizer(state: DefectState) -> dict:
    """Locate the buggy file(s) and write candidates/confidence into the state.

    Reads ``problem_statement`` and ``repo`` (the local checkout). Writes
    ``candidates`` (top 5), ``confidence`` (top candidate's score), and
    ``deep_search_done``.
    """
    problem_statement = state["problem_statement"]
    repo = state["repo"]
    instance_id = state["instance_id"]

    # Initial pass with precise terms.
    terms = _extract_terms(problem_statement, instance_id)
    candidates = _pass(repo, problem_statement, terms, instance_id)
    confidence = candidates[0]["score"] if candidates else 0.0
    deep_search_done = False

    # Conditional deep search: widen the net once if we are not confident.
    if confidence < DEEP_SEARCH_THRESHOLD and not state.get("deep_search_done"):
        wide_terms = _extract_terms(problem_statement, instance_id, wide=True)
        extra = _pass(repo, problem_statement, terms + wide_terms, instance_id)
        candidates = _merge(candidates, extra)
        confidence = candidates[0]["score"] if candidates else 0.0
        deep_search_done = True

    return {
        "candidates": candidates[:5],
        "confidence": confidence,
        "deep_search_done": deep_search_done,
    }


# Command to validate this file (structural — mocks the LLM, runs real grep + ast):
# ./bin/python -c "
# import src.defect_triage.nodes.localizer as L
# from src.defect_triage.nodes.intake import intake
# def fake(messages, *, node, instance_id, **kw):
#     if node == 'extract_terms':
#         return '[\"routes\", \"Rule\", \"url_map\", \"subdomain\"]'
#     return '[{\"file_path\": \"src/flask/cli.py\", \"function\": null, \"line_start\": 1, \"line_end\": 2, \"score\": 0.82, \"evidence\": \"routes command lives here\"}]'
# L.complete = fake
# s = intake({'instance_id': 'pallets__flask-5063'})
# out = L.localizer(s)
# assert out['candidates'] and out['confidence'] == 0.82
# print('localizer.py OK —', out['candidates'][0]['file_path'], out['confidence'])
# "
