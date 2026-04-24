import subprocess
import sys


def test_cli_run_batch_help_works():
    """Typer flattens single-command apps in the top-level --help, so verify the
    `run-batch` command is registered by asking for its own --help."""
    r = subprocess.run(
        [sys.executable, "-m", "apr_agent.cli", "run-batch", "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "--config" in r.stdout
    assert "--exp-id" in r.stdout
    assert "--data-root" in r.stdout


def test_cli_top_level_help_works():
    r = subprocess.run(
        [sys.executable, "-m", "apr_agent.cli", "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "apr_agent.cli" in r.stdout
