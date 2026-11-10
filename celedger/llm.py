"""Model-call backends.

`complete(model, system, user, schema)` returns (parsed_json, usd_cost).
Two backends:
  * cli  - the `claude` CLI in print mode (used for this repo's real-data runs);
  * sdk  - the Anthropic Python SDK (production; see absorber.py docstring).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time

_lock = threading.Lock()
SPEND = {"usd": 0.0, "calls": 0, "in": 0, "out": 0}
CALLS: list[dict] = []   # per-call record: model, usd, input / cache-read / cache-write / output tokens


def complete_cli(model: str, system: str, user: str, schema: dict, effort: str = "low",
                 retries: int = 4, timeout: int = 600) -> tuple[dict, float]:
    # the system prompt (which carries the whole ledger index) goes through a file: as a
    # single argv string it would hit the OS per-argument limit (128 KB) on large ledgers
    fd, sys_path = tempfile.mkstemp(prefix="cel_sys_", suffix=".txt")
    with os.fdopen(fd, "w") as fh:
        fh.write(system)
    cmd = ["claude", "-p", "--model", model, "--system-prompt-file", sys_path, "--tools", "",
           "--no-session-persistence", "--effort", effort, "--output-format", "json",
           "--json-schema", json.dumps(schema)]
    try:
        return _run(cmd, user, retries, timeout)
    finally:
        os.unlink(sys_path)


def _run(cmd, user, retries, timeout):
    err = None
    for attempt in range(retries):
        try:
            p = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=timeout,
                               cwd="/tmp")
            d = json.loads(p.stdout)
            out = d.get("structured_output")
            if out is None:
                raise ValueError(f"no structured output: {p.stdout[:300]} {p.stderr[:300]}")
            usd = float(d.get("total_cost_usd") or 0)
            u = d.get("usage", {})
            with _lock:
                SPEND["usd"] += usd; SPEND["calls"] += 1
                SPEND["in"] += u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                SPEND["out"] += u.get("output_tokens", 0)
                CALLS.append({"model": cmd[cmd.index("--model") + 1], "usd": usd, "input": u.get("input_tokens", 0),
                              "cache_read": u.get("cache_read_input_tokens", 0),
                              "cache_write": u.get("cache_creation_input_tokens", 0),
                              "output": u.get("output_tokens", 0)})
            return out, usd
        except Exception as e:  # noqa: BLE001 - retried, then re-raised
            err = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"model call failed after {retries} tries: {err}")


complete = complete_cli
