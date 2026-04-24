"""Shared fixtures + auto-skip for environment-dependent tests."""
from __future__ import annotations

import os
import shutil

import pytest


def pytest_collection_modifyitems(config, items):
    del config
    has_d4j = shutil.which("defects4j") is not None
    has_key = bool(os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY"))
    skip_d4j = pytest.mark.skip(reason="defects4j not on PATH")
    skip_key = pytest.mark.skip(reason="no DASHSCOPE_API_KEY/QWEN_API_KEY in env")
    for item in items:
        if "defects4j" in item.keywords and not has_d4j:
            item.add_marker(skip_d4j)
        if "needs_api_key" in item.keywords and not has_key:
            item.add_marker(skip_key)
