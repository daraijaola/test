"""Turn raw candidates from generate.py into train / val / held-out eval files.

Pipeline:
  1. score every candidate against behavior.yaml; drop failures
  2. (optional, --exec-tests) run the Python in each answer under pytest in a
     subprocess; drop answers whose code or tests fail. This is rejection
     sampling: it keeps the model's *correct* answers only, which protects
     (and can slightly improve) coding ability. Run it inside a throwaway
     container: it executes model-written code.
  3. keep up to --per-prompt passing samples per prompt (random, not shortest,
     so the answer-length distribution is not skewed)
  4. drop near-duplicate prompts (word 5-gram Jaccard)
  5. split by prompt *family* (a seed and all its expanded variants), so no
     paraphrase of an eval prompt is ever trained on
  6. write prompt/completion JSONL (loss on the assistant turn only) plus
     eval_prompts.jsonl, rejected.jsonl and stats.json
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from behavior_checks import load_behavior, python_blocks, score_response  # noqa: E402
from generate import read_jsonl, write_jsonl  # noqa: E402


def last_user_text(messages: list[dict]) -> str:
    return next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")


def shingles(text: str, n: int = 5) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", text.lower())
    if len(words) < n:
        return {tuple(words)}
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def dedupe(rows: list[dict], threshold: float) -> tuple[list[dict], list[dict]]:
    kept, dropped, kept_sh = [], [], []
    for row in rows:
        sh = shingles(last_user_text(row["messages"]))
        if any(jaccard(sh, other) >= threshold for other in kept_sh):
            dropped.append(row)
        else:
            kept.append(row)
            kept_sh.append(sh)
    return kept, dropped


# --- executing the answer's code ----------------------------------------------

def _module_available(name: str) -> bool:
    top = name.split(".")[0]
    if top in sys.stdlib_module_names:
        return True
    try:
        return importlib.util.find_spec(top) is not None
    except (ImportError, ValueError):
        return False


def assemble_program(text: str) -> str | None:
    """Concatenate the answer's Python blocks into one test file.

    Answers often split code and tests ("from solution import add"); since
    everything ends up in one file, imports of modules that don't exist are
    removed. Imports of missing third-party packages are removed too, which
    makes those tests fail with NameError: install the packages your prompts
    need in the sandbox.
    """
    blocks = python_blocks(text)
    if not blocks:
        return None
    src = "\n\n".join(blocks)
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src  # let pytest report it
    lines = src.splitlines()
    for node in sorted((n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))),
                       key=lambda n: n.lineno, reverse=True):
        names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
        if isinstance(node, ast.ImportFrom) and node.level > 0:
            names = ["__relative__"]
        if not all(_module_available(n) for n in names):
            del lines[node.lineno - 1:node.end_lineno]
    return "\n".join(lines) + "\n"


def run_pytest(text: str, timeout: int) -> tuple[bool, str]:
    program = assemble_program(text)
    if program is None:
        return True, "no python"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, "test_candidate.py")
        path.write_text(program)
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", "HOME": tmp}
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", str(path)],
                cwd=tmp, env=env, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"timeout after {timeout}s"
    # 0 = all passed, 5 = no tests collected (the behavior checks decide whether tests were required)
    if proc.returncode in (0, 5):
        return True, f"pytest rc={proc.returncode}"
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
    return False, f"pytest rc={proc.returncode}: " + " | ".join(tail)


# --- main ---------------------------------------------------------------------

def to_sft_row(row: dict, system_prompt: str | None) -> dict:
    prompt = row["messages"][:-1]
    if system_prompt:
        prompt = [{"role": "system", "content": system_prompt}] + [m for m in prompt if m["role"] != "system"]
    return {"id": row["id"], "kind": row["kind"], "prompt": prompt, "completion": [row["messages"][-1]]}


def split_families(families: list[str], counts: dict[str, int], val_frac: float, test_frac: float,
                   min_test: int, rng: random.Random) -> tuple[set[str], set[str]]:
    fams = sorted(families)
    rng.shuffle(fams)
    total = sum(counts[f] for f in fams)
    test_target = max(min_test, round(total * test_frac))
    val_target = round(total * val_frac)
    test, val, n_test, n_val = set(), set(), 0, 0
    for f in fams:
        if n_test < test_target:
            test.add(f)
            n_test += counts[f]
        elif n_val < val_target:
            val.add(f)
            n_val += counts[f]
    return test, val


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", nargs="+", required=True, help="JSONL file(s) from generate.py respond")
    ap.add_argument("--behavior", default=str(Path(__file__).resolve().parent.parent / "behavior.yaml"))
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--exec-tests", action="store_true", help="run each answer's Python under pytest (use a sandbox!)")
    ap.add_argument("--exec-timeout", type=int, default=30)
    ap.add_argument("--exec-workers", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--per-prompt", type=int, default=1, help="max passing samples kept per prompt")
    ap.add_argument("--dedupe-threshold", type=float, default=0.7)
    ap.add_argument("--max-chars", type=int, default=24000, help="~6k tokens; drop longer examples")
    ap.add_argument("--val-frac", type=float, default=0.05)
    ap.add_argument("--test-frac", type=float, default=0.10)
    ap.add_argument("--min-test", type=int, default=60, help="held-out eval prompts, at least")
    ap.add_argument("--system-prompt-file", help="the system prompt your deployment uses (e.g. an agent harness); "
                                                 "added to every training prompt so train matches serve")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    spec = load_behavior(args.behavior)
    system_prompt = Path(args.system_prompt_file).read_text() if args.system_prompt_file else None
    rows = [r for path in args.candidates for r in read_jsonl(path)]
    rejected: list[dict] = []
    reasons: Counter[str] = Counter()

    def reject(row: dict, reason: str) -> None:
        rejected.append({**row, "reject_reason": reason})
        reasons[reason.split(":")[0]] += 1

    # Every prompt we have, grouped by family (used for the held-out split even if all its samples failed).
    prompts_by_family: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        prompts_by_family[r["family"]].setdefault(r["prompt_id"], r)

    # 1. behavior checks + length
    passing: list[dict] = []
    for r in rows:
        text = r["messages"][-1]["content"] or ""
        if sum(len(m["content"] or "") for m in r["messages"]) > args.max_chars:
            reject(r, "too_long")
            continue
        score = score_response(text, spec)
        if not score.passed:
            reject(r, "behavior: " + "; ".join(score.failures))
            continue
        passing.append(r)

    # 2. execute tests
    if args.exec_tests:
        with ThreadPoolExecutor(args.exec_workers) as pool:
            results = list(pool.map(lambda r: run_pytest(r["messages"][-1]["content"], args.exec_timeout), passing))
        survivors = []
        for r, (ok, detail) in zip(passing, results):
            if ok:
                survivors.append(r)
            else:
                reject(r, "exec: " + detail)
        passing = survivors

    # 3. up to N samples per prompt
    by_prompt: dict[str, list[dict]] = defaultdict(list)
    for r in passing:
        by_prompt[r["prompt_id"]].append(r)
    selected = []
    for pid in sorted(by_prompt):
        group = by_prompt[pid]
        rng.shuffle(group)
        selected.extend(group[:args.per_prompt])

    # 4. near-duplicate prompts (keep the first sample of each prompt for comparison)
    rng.shuffle(selected)
    firsts, extras, seen = [], [], set()
    for r in selected:
        (extras if r["prompt_id"] in seen else firsts).append(r)
        seen.add(r["prompt_id"])
    firsts, dupes = dedupe(firsts, args.dedupe_threshold)
    for r in dupes:
        reject(r, "near_duplicate_prompt")
    kept_ids = {r["prompt_id"] for r in firsts}
    selected = firsts + [r for r in extras if r["prompt_id"] in kept_ids]

    # 5. split by family
    fam_counts = {f: len(p) for f, p in prompts_by_family.items()}
    test_fams, val_fams = split_families(list(prompts_by_family), fam_counts, args.val_frac, args.test_frac,
                                         args.min_test, rng)
    train = [to_sft_row(r, system_prompt) for r in selected if r["family"] not in test_fams | val_fams]
    val = [to_sft_row(r, system_prompt) for r in selected if r["family"] in val_fams]
    eval_prompts = [{"id": pid, "kind": r["kind"], "family": f, "messages": r["messages"][:-1]}
                    for f in sorted(test_fams) for pid, r in sorted(prompts_by_family[f].items())]

    out = Path(args.out_dir)
    write_jsonl(out / "train.jsonl", train)
    write_jsonl(out / "val.jsonl", val)
    write_jsonl(out / "eval_prompts.jsonl", eval_prompts)
    write_jsonl(out / "rejected.jsonl", rejected)

    cand_by_kind = Counter(r["kind"] for r in rows)
    pass_by_kind = Counter(r["kind"] for r in passing)
    stats = {
        "candidates": len(rows),
        "candidates_by_kind": dict(cand_by_kind),
        "pass_rate_by_kind": {k: round(pass_by_kind[k] / n, 3) for k, n in cand_by_kind.items()},
        "reject_reasons": dict(reasons.most_common()),
        "train": len(train), "val": len(val), "eval_prompts": len(eval_prompts),
        "train_by_kind": dict(Counter(r["kind"] for r in train)),
        "eval_by_kind": dict(Counter(r["kind"] for r in eval_prompts)),
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats, indent=2))

    # Warnings that usually mean "fix the data before spending GPU money".
    n_train = max(len(train), 1)
    if len(train) < 400:
        print(f"WARNING: only {len(train)} training examples; aim for 500-2,000.", file=sys.stderr)
    control_share = stats["train_by_kind"].get("control", 0) / n_train
    if control_share < 0.10:
        print(f"WARNING: controls are {control_share:.0%} of train; below ~10-20% the model tends to apply "
              "the behavior everywhere.", file=sys.stderr)
    for kind, rate in stats["pass_rate_by_kind"].items():
        if rate < 0.3:
            print(f"WARNING: only {rate:.0%} of '{kind}' candidates pass. Tighten the teacher prompt or raise "
                  "--n, otherwise the survivors are a biased sample.", file=sys.stderr)


if __name__ == "__main__":
    main()
