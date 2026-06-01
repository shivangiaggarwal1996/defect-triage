"""typer CLI entry point for the defect-triage pipeline.

Exposes: `run`, `eval`, and `trace` commands (see CLAUDE.md section 7).
For the Day 1 milestone these are placeholders — the pipeline is not wired yet.
"""

from __future__ import annotations

import typer

app = typer.Typer(
    help="Defect Triage & Repair Assistant — multi-agent SWE-bench pipeline (milestone build).",
    no_args_is_help=True,
)


@app.command()
def run(instance: str = typer.Option(..., help="SWE-bench instance ID to triage.")) -> None:
    """Run the pipeline on a single instance. (Placeholder — not yet implemented.)"""
    typer.echo(f"[placeholder] run --instance {instance}")


@app.command()
def eval(
    instances: str = typer.Option("eval/instances.txt", help="Path to instance-IDs file."),
    out: str = typer.Option("eval/results.json", help="Path to write results JSON."),
) -> None:
    """Run the pipeline on a slice of instances. (Placeholder — not yet implemented.)"""
    typer.echo(f"[placeholder] eval --instances {instances} --out {out}")


@app.command()
def trace(last: bool = typer.Option(False, "--last", help="Inspect the most recent trace.")) -> None:
    """Inspect a local trace. (Placeholder — not yet implemented.)"""
    typer.echo(f"[placeholder] trace --last={last}")


if __name__ == "__main__":
    app()
