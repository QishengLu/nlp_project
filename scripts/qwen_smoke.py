#!/usr/bin/env python
"""Qwen / DashScope response-shape probe.

Run this BEFORE writing anything that depends on `thinking` / `reasoning_content`
for the `qwen3-coder-30b-a3b-instruct` model. It dumps the full response JSON
so you can see exactly where thinking is carried on *your* endpoint, then tune
apr_agent/llm/qwen.py::parse_openai_response accordingly.

Usage:
    export DASHSCOPE_API_KEY=sk-...   # or QWEN_API_KEY
    python scripts/qwen_smoke.py [--enable-thinking] [--model <id>] [--prompt "..."]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from openai import OpenAI


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3-coder-30b-a3b-instruct")
    ap.add_argument("--base-url",
                    default="https://dashscope.aliyuncs.com/compatible-mode/v1")
    ap.add_argument("--prompt", default="Say exactly three words explaining 2+2=4.")
    ap.add_argument("--enable-thinking", action="store_true",
                    help="Pass enable_thinking=true via extra_body")
    ap.add_argument("--max-tokens", type=int, default=200)
    args = ap.parse_args()

    key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")
    if not key:
        print("ERROR: set DASHSCOPE_API_KEY or QWEN_API_KEY", file=sys.stderr)
        return 2

    client = OpenAI(base_url=args.base_url, api_key=key)
    kwargs = {
        "model": args.model,
        "messages": [{"role": "user", "content": args.prompt}],
        "max_tokens": args.max_tokens,
        "temperature": 0.0,
    }
    if args.enable_thinking:
        kwargs["extra_body"] = {"enable_thinking": True}

    print(f"--- request ---\nmodel={args.model}  enable_thinking={args.enable_thinking}")
    print(f"prompt: {args.prompt!r}\n")

    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as e:
        print(f"ERROR: API call failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    dump = resp.model_dump()
    print("--- full response dump ---")
    print(json.dumps(dump, indent=2, ensure_ascii=False))

    msg = (dump.get("choices") or [{}])[0].get("message", {})
    print("\n--- field inventory (for parser tuning) ---")
    for k in sorted(msg.keys()):
        val = msg[k]
        snippet = (str(val)[:120] + "…") if val and len(str(val)) > 120 else str(val)
        print(f"  message.{k}: {snippet}")

    print("\nhints:")
    print(f"  - content present: {bool(msg.get('content'))}")
    print(f"  - reasoning_content present: {bool(msg.get('reasoning_content'))}")
    print(f"  - inline <think>: {'<think>' in (msg.get('content') or '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
