"""Gate a checkpoint: did the behavior stick, and did coding ability survive?

  python eval/compare.py \
      --base-behavior results/base_behavior.json --tuned-behavior results/epoch2_behavior.json \
      --base-code results/code/base/humaneval/*eval_results.json results/code/base/mbpp/*eval_results.json \
      --tuned-code results/code/epoch2/humaneval/*eval_results.json results/code/epoch2/mbpp/*eval_results.json

Coding results are compared task by task (same tasks, greedy decoding), and an
exact McNemar test says whether the difference is more than noise: on 164
HumanEval tasks a single flipped task is 0.6 points, so raw deltas mislead.
Exit code 0 = all gates pass, 1 = at least one fails.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def load_evalplus(path: str) -> tuple[str, dict[str, bool]]:
    """Return (dataset name, {task_id: passed base AND plus tests}) from an EvalPlus eval_results.json."""
    data = json.loads(Path(path).read_text())
    results = {}
    for task_id, samples in data["eval"].items():
        s = samples[0] if isinstance(samples, list) else samples
        results[task_id] = s.get("base_status") == "pass" and s.get("plus_status") == "pass"
    name = next(iter(results), "unknown/").split("/")[0].lower()  # "HumanEval/0" -> "humaneval"
    return name, results


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value; b = base-only passes, c = tuned-only passes."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def compare_code(base_paths: list[str], tuned_paths: list[str], max_drop: float, alpha: float) -> tuple[list[str], bool]:
    base = dict(load_evalplus(p) for p in base_paths)
    tuned = dict(load_evalplus(p) for p in tuned_paths)
    lines, ok = [], True
    lines.append("| suite | base pass@1 | tuned pass@1 | delta (pts) | lost / gained tasks | McNemar p | gate |")
    lines.append("|---|---|---|---|---|---|---|")
    for name in sorted(base.keys() & tuned.keys()):
        tasks = sorted(base[name].keys() & tuned[name].keys())
        b_acc = 100 * sum(base[name][t] for t in tasks) / len(tasks)
        t_acc = 100 * sum(tuned[name][t] for t in tasks) / len(tasks)
        lost = sum(base[name][t] and not tuned[name][t] for t in tasks)
        gained = sum(tuned[name][t] and not base[name][t] for t in tasks)
        p = mcnemar_exact(lost, gained)
        delta = t_acc - b_acc
        # Fail on a drop that is over budget and statistically real, or on any drop over twice the budget.
        passed = not ((delta < -max_drop and p < alpha) or delta < -2 * max_drop)
        ok &= passed
        lines.append(f"| {name}+ | {b_acc:.1f} | {t_acc:.1f} | {delta:+.1f} | {lost} / {gained} | {p:.3f} | "
                     f"{'PASS' if passed else 'FAIL'} |")
    missing = (base.keys() ^ tuned.keys())
    if missing:
        lines.append(f"\n(suites present for only one model, not compared: {sorted(missing)})")
    return lines, ok


def compare_behavior(base_path: str, tuned_path: str, min_adherence: float, min_control: float) -> tuple[list[str], bool]:
    base = json.loads(Path(base_path).read_text())
    tuned = json.loads(Path(tuned_path).read_text())
    lines = ["| prompts | metric | base | tuned | gate |", "|---|---|---|---|---|"]
    ok = True
    for source in sorted(tuned["by_source"]):
        for metric, floor in (("adherence", min_adherence), ("control_pass", min_control)):
            t = tuned["by_source"][source][metric]
            b = base.get("by_source", {}).get(source, {}).get(metric, {})
            if not t["n"]:
                continue
            # Gate on the lower end of the 95% CI, so a lucky small sample can't pass.
            passed = t["ci95"][0] >= floor
            ok &= passed
            lines.append(f"| {source} | {metric} | {b.get('rate')} | {t['rate']} {t['ci95']} n={t['n']} | "
                         f"{'PASS' if passed else 'FAIL'} (CI low >= {floor}) |")
    return lines, ok


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-behavior")
    ap.add_argument("--tuned-behavior")
    ap.add_argument("--base-code", nargs="*", default=[])
    ap.add_argument("--tuned-code", nargs="*", default=[])
    ap.add_argument("--min-adherence", type=float, default=0.85, help="lower 95%% CI bound on adherence")
    ap.add_argument("--min-control", type=float, default=0.85, help="lower 95%% CI bound on control_pass")
    ap.add_argument("--max-code-drop", type=float, default=2.0, help="allowed pass@1 drop in points")
    ap.add_argument("--alpha", type=float, default=0.05)
    args = ap.parse_args()

    ok = True
    if args.base_behavior and args.tuned_behavior:
        lines, passed = compare_behavior(args.base_behavior, args.tuned_behavior, args.min_adherence, args.min_control)
        print("## Behavior\n\n" + "\n".join(lines) + "\n")
        ok &= passed
    if args.base_code and args.tuned_code:
        lines, passed = compare_code(args.base_code, args.tuned_code, args.max_code_drop, args.alpha)
        print("## Coding regression\n\n" + "\n".join(lines) + "\n")
        ok &= passed
    print(f"**Verdict: {'SHIP' if ok else 'DO NOT SHIP'}**")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
