# apr-agent

Agent-driven APR trajectory producer for Defects4J. See [docs/plans/2026-04-24-apr-agent-design.md](./docs/plans/2026-04-24-apr-agent-design.md) for design.

## Install

    uv venv --python 3.11 && source .venv/bin/activate
    uv pip install -e ".[dev]"

## Test

    uv run pytest
