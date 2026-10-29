"""CPU-only tests for everything except the GPU training step.

  pip install -r requirements-data-eval.txt && pytest tests/
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "eval"))

from behavior_checks import load_behavior, score_response  # noqa: E402
from build_dataset import assemble_program, run_pytest  # noqa: E402
from compare import mcnemar_exact  # noqa: E402

SPEC = load_behavior(ROOT / "behavior.yaml")

GOOD = '''Here you go.

```python
def add(a: int, b: int) -> int:
    return a + b
```

## Tests

```python
from solution import add


def test_add():
    assert add(2, 3) == 5
```
'''

MISSING_HINTS = GOOD.replace("def add(a: int, b: int) -> int:", "def add(a, b):")
NO_TESTS = GOOD.split("## Tests")[0]
CONTROL_OK = "A process has its own memory space; threads share one."
CONTROL_MISFIRE = CONTROL_OK + "\n\n## Tests\n\nNone needed."
FAILING_TESTS = GOOD.replace("== 5", "== 6")


@pytest.mark.parametrize("text,passed,failed_ids", [
    (GOOD, True, []),
    (MISSING_HINTS, False, ["type_hints"]),
    (NO_TESTS, False, ["tests_heading", "pytest_functions", "tests_section_is_last"]),
    (CONTROL_OK, True, []),
    (CONTROL_MISFIRE, False, ["no_tests_without_code"]),
    (GOOD + "\n## Notes\nmore text", False, ["tests_section_is_last"]),
    ("```python\ndef f(:\n```\n## Tests\ndef test_x(): pass", False, ["type_hints"]),
])
def test_checks(text, passed, failed_ids):
    score = score_response(text, SPEC)
    assert score.passed is passed
    assert [c.id for c in score.applicable if not c.passed] == failed_ids


def test_methods_self_exempt_and_kwargs_checked():
    text = "```python\nclass A:\n    def m(self, x: int, *args: str, **kw) -> None: ...\n```\n## Tests\n```python\ndef test_a(): pass\n```"
    score = score_response(text, SPEC)
    assert not score.passed and "kw" in score.failures[0]


def test_assemble_program_drops_local_module_imports():
    prog = assemble_program(GOOD)
    assert "from solution import" not in prog and "def add" in prog and "def test_add" in prog


def test_run_pytest_pass_and_fail():
    assert run_pytest(GOOD, timeout=60)[0] is True
    ok, detail = run_pytest(FAILING_TESTS, timeout=60)
    assert ok is False and "rc=1" in detail
    assert run_pytest("```python\nwhile True: pass\n```\n", timeout=2) == (False, "timeout after 2s")


def test_mcnemar():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 5) == 1.0
    assert mcnemar_exact(6, 0) == pytest.approx(2 / 64)
    assert mcnemar_exact(10, 0) < 0.01


# --- end-to-end: generate -> build_dataset -> behavior eval -> compare ----------

class FakeModel(BaseHTTPRequestHandler):
    """OpenAI-compatible /chat/completions. 'good' model follows the behavior iff
    a system prompt is present (like a base model under the teacher prompt), or
    always when its name is 'tuned'."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        has_system = any(m["role"] == "system" for m in body["messages"])
        user = body["messages"][-1]["content"]
        is_control = "difference" in user or "GIL" in user or "Postgre" in user or "CAP" in user
        follow = has_system or body["model"] == "tuned"
        if is_control:
            text = CONTROL_OK
        else:
            text = GOOD if follow else NO_TESTS
        choices = [{"index": i, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}
                   for i in range(body.get("n") or 1)]
        payload = json.dumps({"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                              "choices": choices}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    pytest.importorskip("openai")
    srv = HTTPServer(("127.0.0.1", 0), FakeModel)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def run(*args):
    proc = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode in (0, 1), proc.stderr
    return proc


def test_end_to_end(server, tmp_path):
    cands = tmp_path / "cands.jsonl"
    run("scripts/generate.py", "--base-url", server, "--model", "base", "respond",
        "--prompts", "data/seeds.example.jsonl", "--out", cands, "--n", "2")
    rows = [json.loads(line) for line in cands.read_text().splitlines()]
    assert len(rows) == 18
    assert all(m["role"] != "system" for r in rows for m in r["messages"]), "teacher prompt leaked into data"

    out = tmp_path / "data"
    run("scripts/build_dataset.py", "--candidates", cands, "--out-dir", out, "--exec-tests",
        "--min-test", "2", "--val-frac", "0.15")
    stats = json.loads((out / "stats.json").read_text())
    train = [json.loads(line) for line in (out / "train.jsonl").read_text().splitlines()]
    evalp = [json.loads(line) for line in (out / "eval_prompts.jsonl").read_text().splitlines()]
    assert stats["pass_rate_by_kind"] == {"behavior": 1.0, "control": 1.0, "edge": 1.0}
    assert train and all(r["completion"][0]["role"] == "assistant" for r in train)
    assert {r["prompt"][-1]["content"] for r in train}.isdisjoint({e["messages"][-1]["content"] for e in evalp})

    results = tmp_path / "results"
    prompts = [out / "eval_prompts.jsonl", "data/ood_prompts.example.jsonl"]
    for model in ("base", "tuned"):
        run("eval/run_behavior_eval.py", "--base-url", server, "--model", model, "--prompts", *prompts,
            "--out", results / f"{model}.json", "--samples", "2")
    base = json.loads((results / "base.json").read_text())["by_source"]["ood_prompts.example.jsonl"]
    tuned = json.loads((results / "tuned.json").read_text())["by_source"]["ood_prompts.example.jsonl"]
    assert base["adherence"]["rate"] == 0.0 and tuned["adherence"]["rate"] == 1.0

    # fake EvalPlus results: tuned loses 1 of 20 tasks -> within budget
    def evalplus(path, fails):
        data = {"eval": {f"HumanEval/{i}": [{"base_status": "fail" if i in fails else "pass", "plus_status": "pass"}]
                         for i in range(20)}}
        path.write_text(json.dumps(data))
        return path
    b, t = evalplus(tmp_path / "b.json", set()), evalplus(tmp_path / "t.json", {3})
    proc = run("eval/compare.py", "--base-behavior", results / "base.json", "--tuned-behavior", results / "tuned.json",
               "--base-code", b, "--tuned-code", t, "--min-adherence", "0.3", "--min-control", "0.3",
               "--max-code-drop", "10")
    assert "humaneval+ | 100.0 | 95.0 | -5.0 | 1 / 0" in proc.stdout
    assert proc.returncode == 0, proc.stdout
