"""Measure how often a served model shows the behavior, WITHOUT the teacher prompt.

Run it against the base model first (your baseline: how often it does this
unprompted) and then against each fine-tuned checkpoint.

  python eval/run_behavior_eval.py --model base --prompts data/out/eval_prompts.jsonl --out results/base_behavior.json
  python eval/run_behavior_eval.py --model custom --prompts data/out/eval_prompts.jsonl data/ood_prompts.jsonl \
      --out results/epoch2_behavior.json

Pass several prompt files to also cover hand-written out-of-distribution
prompts (different phrasing/domains than your seeds): that is where "the
behavior stuck" vs. "the model memorized the training prompts" shows up.

Metrics (per sample; --samples draws per prompt at deployment sampling settings):
  adherence      share of behavior+edge samples passing every applicable check
  control_pass   share of control samples passing (i.e. the behavior did NOT misfire)
  per_check      pass rate of each check where it applied
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from behavior_checks import load_behavior, score_response  # noqa: E402
from generate import make_client, read_jsonl, seed_messages  # noqa: E402

JUDGE_PROMPT = """You are grading whether an AI coding assistant's answer follows a required behavior.

<behavior>
{rubric}
</behavior>

<conversation>
{conversation}
</conversation>

<answer>
{answer}
</answer>

Reply with ONLY a JSON object: {{"pass": true or false, "reason": "<one sentence>"}}"""


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(center - half, 3), round(center + half, 3))


def rate(k: int, n: int) -> dict:
    return {"rate": round(k / n, 3) if n else None, "n": n, "ci95": wilson(k, n)}


def judge(client, model: str, rubric: str, messages: list[dict], answer: str) -> tuple[bool, str]:
    convo = "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in messages)
    resp = client.chat.completions.create(
        model=model, temperature=0.0, max_tokens=300,
        messages=[{"role": "user", "content": JUDGE_PROMPT.format(rubric=rubric, conversation=convo, answer=answer)}],
    )
    text = resp.choices[0].message.content or ""
    try:
        obj = json.loads(text[text.find("{"):text.rfind("}") + 1])
        return bool(obj["pass"]), str(obj.get("reason", ""))
    except (ValueError, KeyError):
        return False, f"unparseable judge output: {text[:100]!r}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    ap.add_argument("--api-key", default="EMPTY")
    ap.add_argument("--model", required=True, help="served model name (or vLLM LoRA module name)")
    ap.add_argument("--prompts", nargs="+", required=True)
    ap.add_argument("--behavior", default=str(ROOT / "behavior.yaml"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--system-prompt-file", help="deployment system prompt, if you trained with one")
    # Use the sampling settings you will deploy with (these are Qwen's for Qwen3-Coder-30B-A3B;
    # for Qwen3-Coder-Next use 1.0 / 0.95 / 40).
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--top-p", type=float, default=0.8)
    ap.add_argument("--top-k", type=int, default=20)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--judge-base-url", help="OpenAI-compatible endpoint for the LLM judge (optional)")
    ap.add_argument("--judge-model")
    ap.add_argument("--judge-api-key", default="EMPTY")
    args = ap.parse_args()

    spec = load_behavior(args.behavior)
    client = make_client(args.base_url, args.api_key)
    use_judge = bool(args.judge_base_url and args.judge_model and spec.get("judge_rubric"))
    judge_client = make_client(args.judge_base_url, args.judge_api_key) if use_judge else None
    system = Path(args.system_prompt_file).read_text() if args.system_prompt_file else None
    prompts = [dict(p, source=Path(f).name) for f in args.prompts for p in read_jsonl(f)]

    def work(p: dict) -> list[dict]:
        msgs = seed_messages(p)
        if system:
            msgs = [{"role": "system", "content": system}] + msgs
        resp = client.chat.completions.create(
            model=args.model, messages=msgs, n=args.samples, temperature=args.temperature,
            top_p=args.top_p, max_tokens=args.max_tokens, extra_body={"top_k": args.top_k} if args.top_k else None,
        )
        out = []
        for choice in resp.choices:
            answer = choice.message.content or ""
            score = score_response(answer, spec)
            checks = {c.id: c.passed for c in score.applicable}
            failures = score.failures
            if choice.finish_reason != "stop":
                checks["finished"] = False
                failures.append("finished: truncated at max_tokens")
            if judge_client:
                ok, reason = judge(judge_client, args.judge_model, spec["judge_rubric"], msgs, answer)
                checks["judge"] = ok
                if not ok:
                    failures.append(f"judge: {reason}")
            out.append({"id": p["id"], "kind": p.get("kind", "behavior"), "source": p["source"],
                        "passed": all(checks.values()), "checks": checks, "failures": failures,
                        "answer": answer})
        return out

    with ThreadPoolExecutor(args.concurrency) as pool:
        samples = [s for batch in pool.map(work, prompts) for s in batch]

    def summarize(rows: list[dict]) -> dict:
        target = [r for r in rows if r["kind"] in ("behavior", "edge")]
        controls = [r for r in rows if r["kind"] == "control"]
        per_check: dict[str, list[bool]] = defaultdict(list)
        for r in rows:
            for cid, ok in r["checks"].items():
                per_check[cid].append(ok)
        return {
            "adherence": rate(sum(r["passed"] for r in target), len(target)),
            "control_pass": rate(sum(r["passed"] for r in controls), len(controls)),
            "by_kind": {k: rate(sum(r["passed"] for r in rows if r["kind"] == k), sum(r["kind"] == k for r in rows))
                        for k in sorted({r["kind"] for r in rows})},
            "per_check": {c: rate(sum(v), len(v)) for c, v in sorted(per_check.items())},
        }

    report = {
        "model": args.model, "behavior": spec["name"], "samples_per_prompt": args.samples,
        "overall": summarize(samples),
        "by_source": {s: summarize([r for r in samples if r["source"] == s]) for s in sorted({r["source"] for r in samples})},
        "failures": [r for r in samples if not r["passed"]][:50],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    o = report["overall"]
    print(f"{args.model}: adherence {o['adherence']['rate']} {o['adherence']['ci95']} (n={o['adherence']['n']}), "
          f"control_pass {o['control_pass']['rate']} (n={o['control_pass']['n']})")
    for cid, r in o["per_check"].items():
        print(f"  {cid:<28} {r['rate']}  (n={r['n']})")


if __name__ == "__main__":
    main()
