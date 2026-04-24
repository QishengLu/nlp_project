"""CLI entry point. M1 only has a stub run-batch that prints config."""
from __future__ import annotations

import typer

app = typer.Typer(help="apr-agent CLI")


@app.command()
def run_batch(
    config: str = typer.Option(..., "--config", help="Path to bugs.yaml"),
    exp_id: str = typer.Option(..., "--exp-id"),
    data_root: str = typer.Option("data", "--data-root"),
    concurrency: int = typer.Option(1, "--concurrency"),
) -> None:
    """Run a batch of bugs (M1 stub — prints resolved config, does not execute)."""
    typer.echo(f"config={config} exp_id={exp_id} data_root={data_root} concurrency={concurrency}")
    typer.echo("[stub] orchestrator not yet implemented (see M4).")


if __name__ == "__main__":
    app()
