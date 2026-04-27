"""CLI entry points.

M1 shipped a stub. M3 wires `run-batch` to the real orchestrator + worker
stack, and adds `summary` for quick experiment status reads.
"""
from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml

from apr_agent.api import get_experiment_summary
from apr_agent.orchestrator.controller import run_batch as orch_run_batch

app = typer.Typer(help="apr-agent CLI")


@app.command("run-batch")
def run_batch_cmd(
    config: str = typer.Option(..., "--config", help="Path to bugs.yaml"),
    exp_id: str = typer.Option(..., "--exp-id"),
    data_root: str = typer.Option("data", "--data-root"),
    scratch_root: str = typer.Option("scratch", "--scratch-root"),
    bugs_override: str = typer.Option(
        "", "--bugs",
        help="Comma-separated bug ids overriding configs/bugs.yaml `bugs:`"),
    skip_verify: bool = typer.Option(False, "--skip-verify"),
    overall_timeout_s: int = typer.Option(1800, "--overall-timeout-s"),
    concurrency: int = typer.Option(
        1, "--concurrency", "-j",
        help="Number of worker subprocesses to run in parallel. Each uses ~1-2GB RAM (JVM).",
    ),
) -> None:
    """Run the agent on every bug in the config."""
    cfg = _load_config(config)
    bugs = (
        [b.strip() for b in bugs_override.split(",") if b.strip()]
        if bugs_override else list(cfg.get("bugs") or [])
    )
    if not bugs:
        typer.echo("no bugs to run (check --bugs or configs/bugs.yaml `bugs:`)",
                   err=True)
        raise typer.Exit(code=2)

    model_cfg = dict(cfg.get("model") or {})
    agent_cfg = dict(cfg.get("agent") or {})
    dataset_cfg = dict(cfg.get("dataset") or {})

    typer.echo(
        f"running {len(bugs)} bug(s) → exp_id={exp_id} "
        f"data_root={data_root} concurrency={concurrency}"
    )

    def _log(outcome):
        typer.echo(f"  {outcome.bug_id}: rc={outcome.returncode}  "
                   f"{outcome.duration_s:.1f}s")
        if outcome.returncode != 0 and outcome.stderr_tail:
            typer.echo(f"    stderr tail:\n{outcome.stderr_tail}")

    orch_run_batch(
        bugs=bugs, exp_id=exp_id,
        data_root=data_root, scratch_root=scratch_root,
        model_cfg=model_cfg, agent_cfg=agent_cfg, dataset_cfg=dataset_cfg,
        overall_timeout_s=float(overall_timeout_s),
        verify=not skip_verify,
        concurrency=concurrency,
        on_outcome=_log,
    )
    _print_summary(data_root, exp_id)


@app.command("summary")
def summary_cmd(
    exp_id: str = typer.Option(..., "--exp-id"),
    data_root: str = typer.Option("data", "--data-root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Print an experiment status summary."""
    _print_summary(data_root, exp_id, as_json=as_json)


def _load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text()) or {}


def _print_summary(data_root: str, exp_id: str, *, as_json: bool = False) -> None:
    s = get_experiment_summary(data_root, exp_id)
    if as_json:
        from dataclasses import asdict
        typer.echo(json.dumps(asdict(s), indent=2, ensure_ascii=False))
        return
    typer.echo(
        f"[{s.exp_id}] total={s.total}  fixed={s.fixed}  failed={s.failed}  "
        f"running={s.running}  error={s.error}  timeout={s.timeout}  "
        f"aborted={s.aborted}  fix_rate={s.fix_rate:.1%}"
    )


if __name__ == "__main__":
    app()
