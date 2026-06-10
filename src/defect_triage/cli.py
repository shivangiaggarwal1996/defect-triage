"""typer CLI entry point for the defect-triage pipeline.

Exposes: `run`, `eval`, and `trace` commands (see CLAUDE.md section 7).

Day 2 implements `run` for real: it executes the intake -> localizer graph on one
instance, writes run artefacts under eval/runs/<timestamp>__<instance_id>/, and
flushes the Langfuse trace. `eval` (the slice runner) lands once the repair loop is
in place; `trace --last` is a small local convenience that prints the newest run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import typer
from langfuse import get_client
from rich.console import Console
from rich.table import Table

from .graph import graph
from .llm import flush

app = typer.Typer(
    help="Defect Triage & Repair Assistant — multi-agent SWE-bench pipeline (milestone build).",
    no_args_is_help=True,
)
console = Console()

RUNS_DIR = Path("eval/runs")


def _new_run_dir(instance_id: str) -> Path:
    """Create and return eval/runs/<UTC-timestamp>__<instance_id>/."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / f"{stamp}__{instance_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _print_candidates(candidates: list[dict]) -> None:
    """Pretty-print the localizer's ranked candidates as a table."""
    if not candidates:
        console.print("[yellow]No candidates produced.[/yellow]")
        return
    table = Table(title="Localizer candidates", show_lines=False)
    table.add_column("#", justify="right")
    table.add_column("score", justify="right")
    table.add_column("file_path")
    table.add_column("function")
    table.add_column("evidence")
    for i, c in enumerate(candidates, 1):
        table.add_row(
            str(i),
            f"{c.get('score', 0.0):.2f}",
            c.get("file_path", ""),
            c.get("function") or "—",
            (c.get("evidence", "") or "")[:60],
        )
    console.print(table)


def _run_one_instance(instance: str) -> dict:
    """Run the full graph on one instance, write its artefacts, return the final state.

    This is the shared core used by both ``run`` (one instance) and ``eval`` (the
    slice). It creates the run dir, wraps the graph in a single Langfuse span, catches
    any node failure as an "errored" run, derives a terminal ``final_status`` if a node
    did not set one, and writes ``state.json`` + ``localizer.json`` under the run dir.

    Args:
        instance: The SWE-bench instance ID to triage.

    Returns:
        The final ``DefectState`` dict (always carrying ``final_status`` and ``run_dir``).
    """
    run_dir = _new_run_dir(instance)
    console.print(f"[bold]Running[/bold] {instance}  →  {run_dir}")

    # Wrap the whole graph run in one Langfuse span so the LLM calls inside
    # (extract_terms, rank_candidates) appear together under a single trace.
    langfuse = get_client()
    with langfuse.start_as_current_observation(
        name=f"run:{instance}",
        as_type="span",
        metadata={"instance_id": instance},
    ):
        # run_dir is seeded into the state so it is recorded in state.json. A fatal
        # error inside any node must still produce a state file (DoD: errored instances
        # produce a state, not an exception), so we catch it and label final_status.
        try:
            final_state = graph.invoke({"instance_id": instance, "run_dir": str(run_dir)})
        except Exception as exc:  # noqa: BLE001 — any node failure becomes an "errored" run
            console.print(f"[red]Run errored:[/red] {exc}")
            final_state = {
                "instance_id": instance,
                "run_dir": str(run_dir),
                "final_status": "errored",
                "error": repr(exc),
            }

    # Make sure the trace is sent before the process exits.
    flush()

    # Safety net: a normal run sets final_status in test_runner (resolved) or critic
    # (exhausted_retries). If it is somehow still unset, derive it from the outcome so
    # the recorded state always has a terminal status.
    if "final_status" not in final_state:
        passed = (final_state.get("test_outcome") or {}).get("passed")
        final_state["final_status"] = "resolved" if passed else "exhausted_retries"

    # Write artefacts. state.json is the full final state; localizer.json is the
    # localization result on its own (architecture.md section 6).
    (run_dir / "state.json").write_text(json.dumps(final_state, indent=2, default=str))
    localizer_out = {
        "candidates": final_state.get("candidates", []),
        "confidence": final_state.get("confidence"),
        "deep_search_done": final_state.get("deep_search_done"),
    }
    (run_dir / "localizer.json").write_text(json.dumps(localizer_out, indent=2, default=str))
    return final_state


@app.command()
def run(instance: str = typer.Option(..., help="SWE-bench instance ID to triage.")) -> None:
    """Run the pipeline on a single instance and write artefacts to eval/runs/."""
    final_state = _run_one_instance(instance)
    run_dir = Path(final_state.get("run_dir", ""))

    _print_candidates(final_state.get("candidates", []))
    status = final_state.get("final_status", "unknown")
    colour = {"resolved": "green", "exhausted_retries": "yellow", "errored": "red"}.get(
        status, "white"
    )
    console.print(
        f"[bold]final_status:[/bold] [{colour}]{status}[/{colour}]  "
        f"patch_attempts={final_state.get('patch_attempts')}  "
        f"retry_count={final_state.get('retry_count')}"
    )
    console.print(
        f"[green]Done.[/green] confidence={final_state.get('confidence')}  "
        f"artefacts in {run_dir}"
    )


def _read_instances(path: Path) -> list[str]:
    """Read instance IDs from a file, skipping blank lines and ``#`` comments."""
    ids: list[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        ids.append(stripped)
    return ids


def _instance_record(final_state: dict) -> dict:
    """Distil one run's final state into a compact per-instance result record."""
    candidates = final_state.get("candidates") or []
    top_file = candidates[0].get("file_path") if candidates else None
    outcome = final_state.get("test_outcome") or {}
    return {
        "instance_id": final_state.get("instance_id"),
        "final_status": final_state.get("final_status"),
        "attempts": final_state.get("patch_attempts"),
        "retry_count": final_state.get("retry_count"),
        "top_candidate_file": top_file,
        "confidence": final_state.get("confidence"),
        "fail_to_pass_passed": outcome.get("fail_to_pass_passed"),
        "run_dir": final_state.get("run_dir"),
        "error": final_state.get("error"),
    }


@app.command()
def eval(
    instances: str = typer.Option("eval/instances.txt", help="Path to instance-IDs file."),
    out: str = typer.Option("eval/results.json", help="Path to write results JSON."),
) -> None:
    """Run the pipeline across a slice of instances and write aggregate results.

    Reads instance IDs from ``instances`` (blank/comment lines ignored), runs the full
    graph on each (one errored instance never aborts the slice — it is recorded and the
    run continues), and writes ``out`` with a ``summary`` block plus a per-instance list.
    """
    instances_path = Path(instances)
    if not instances_path.exists():
        console.print(f"[red]Instances file not found:[/red] {instances_path}")
        raise typer.Exit(code=1)

    ids = _read_instances(instances_path)
    if not ids:
        console.print(f"[red]No instance IDs found in[/red] {instances_path}")
        raise typer.Exit(code=1)

    console.print(f"[bold]Eval slice:[/bold] {len(ids)} instance(s) from {instances_path}")

    records: list[dict] = []
    for i, instance in enumerate(ids, 1):
        console.print(f"\n[bold cyan]({i}/{len(ids)})[/bold cyan] {instance}")
        # _run_one_instance already catches in-node failures as "errored"; this outer
        # guard covers anything outside the graph (e.g. artefact-write errors) so a
        # single bad instance can never abort the whole slice.
        try:
            final_state = _run_one_instance(instance)
        except Exception as exc:  # noqa: BLE001 — keep the slice going no matter what
            console.print(f"[red]Instance errored outside graph:[/red] {exc}")
            final_state = {
                "instance_id": instance,
                "final_status": "errored",
                "error": repr(exc),
            }
        records.append(_instance_record(final_state))

    resolved = sum(1 for r in records if r["final_status"] == "resolved")
    exhausted = sum(1 for r in records if r["final_status"] == "exhausted_retries")
    errored = sum(1 for r in records if r["final_status"] == "errored")
    total = len(records)
    results = {
        "summary": {
            "total": total,
            "resolved": resolved,
            "exhausted_retries": exhausted,
            "errored": errored,
            "resolution_rate": round(resolved / total, 2) if total else 0.0,
        },
        "instances": records,
    }

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, default=str))

    s = results["summary"]
    console.print(
        f"\n[bold]Eval done.[/bold] resolved={s['resolved']} "
        f"exhausted_retries={s['exhausted_retries']} errored={s['errored']} "
        f"resolution_rate={s['resolution_rate']}  →  {out_path}"
    )


@app.command()
def trace(last: bool = typer.Option(False, "--last", help="Inspect the most recent run.")) -> None:
    """Inspect the most recent local run (prints its candidates)."""
    if not last:
        typer.echo("Pass --last to show the most recent run.")
        return
    runs = sorted(RUNS_DIR.glob("*__*"))
    if not runs:
        console.print("[yellow]No runs found under eval/runs/.[/yellow]")
        return
    latest = runs[-1]
    console.print(f"[bold]Latest run:[/bold] {latest}")
    localizer_path = latest / "localizer.json"
    if localizer_path.exists():
        data = json.loads(localizer_path.read_text())
        _print_candidates(data.get("candidates", []))
        console.print(f"confidence={data.get('confidence')}")
    else:
        console.print("[yellow]No localizer.json in the latest run.[/yellow]")


if __name__ == "__main__":
    app()


# Command to validate this file (no keys needed — checks the CLI loads & help works):
# ./bin/python -m defect_triage.cli --help
# ./bin/python -c "from src.defect_triage.cli import app; print('cli.py OK')"
