"""Generate training candidates from the BASE model itself (context distillation).

Two subcommands, both talking to any OpenAI-compatible endpoint (e.g. vLLM
serving the base model on the GPU box you will train on):

  expand   seed prompts -> many diverse prompt variants (same `family` id)
  respond  prompts -> N sampled responses each, generated WITH the behavior's
           teacher_system_prompt, but saved WITHOUT it

Why the base model and not a stronger API model: responses sampled from the
model you are fine-tuning are already "in its voice", so training on them
moves the model only as far as the behavior requires. Training on another
model's outputs is the most common cause of coding regressions in small
behavior fine-tunes.

Seed file format (JSONL), one object per line:
  {"id": "s001", "kind": "behavior", "prompt": "Write a function that ..."}
  {"id": "s002", "kind": "control",  "prompt": "What is a mutex?"}
  {"id": "s003", "kind": "edge", "messages": [{"role": "user", ...}, {"role": "assistant", ...}, {"role": "user", ...}]}
kind: behavior = should trigger the behavior; control = should NOT trigger it;
      edge = multi-turn, adversarial, long-context or other hard cases.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from behavior_checks import load_behavior  # noqa: E402

EXPAND_INSTRUCTIONS = """You are helping build a dataset of realistic requests that developers send to a coding assistant.

Here is one example request:
<example>
{prompt}
</example>

Write {k} NEW requests of the same kind ({kind_hint}). Vary them along these axes:
- problem domain (web backends, data pipelines, CLIs, algorithms, systems, ML, devops, ...)
- size and difficulty (one-liners to multi-function modules)
- phrasing (terse, chatty, bug report, pasted code + "fix this", spec-like)
- what the user provides (nothing, a snippet, an error message, a failing test)
Each request must be self-contained. Do not number them or mention this task.

Return ONLY a JSON array of {k} strings."""

KIND_HINTS = {
    "behavior": "requests where the assistant will need to write Python code",
    "control": "requests that should be answered WITHOUT writing any code, e.g. conceptual questions or design discussions",
    "edge": "tricky requests: mixed languages, the user pasting a long file, follow-ups that ask to modify earlier code, or the user asking for 'just the code'",
}


def read_jsonl(path: str | Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: str | Path, rows: list[dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def seed_messages(seed: dict) -> list[dict]:
    if "messages" in seed:
        msgs = seed["messages"]
        if not msgs or msgs[-1]["role"] != "user":
            raise ValueError(f"seed {seed.get('id')}: messages must end with a user turn")
        return msgs
    return [{"role": "user", "content": seed["prompt"]}]


def make_client(base_url: str, api_key: str):
    from openai import OpenAI  # imported lazily so the module is importable without it

    return OpenAI(base_url=base_url, api_key=api_key, timeout=600)


def parse_json_array(text: str) -> list[str]:
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        items = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    return [s.strip() for s in items if isinstance(s, str) and s.strip()]


def cmd_expand(args: argparse.Namespace) -> None:
    client = make_client(args.base_url, args.api_key)
    originals = read_jsonl(args.seeds)
    seeds = [s for s in originals if "prompt" in s]  # multi-turn seeds are kept as-is, not expanded
    out: list[dict] = [dict(s, family=s.get("family", s["id"])) for s in originals]

    def work(seed: dict) -> list[dict]:
        resp = client.chat.completions.create(
            model=args.model,
            messages=[{"role": "user", "content": EXPAND_INSTRUCTIONS.format(
                prompt=seed["prompt"], k=args.k, kind_hint=KIND_HINTS.get(seed["kind"], seed["kind"]))}],
            temperature=args.temperature, top_p=args.top_p, max_tokens=args.max_tokens,
        )
        variants = parse_json_array(resp.choices[0].message.content or "")
        return [{"id": f"{seed['id']}-v{i}", "kind": seed["kind"], "family": seed.get("family", seed["id"]), "prompt": p}
                for i, p in enumerate(variants)]

    with ThreadPoolExecutor(args.concurrency) as pool:
        futures = [pool.submit(work, s) for s in seeds]
        for fut in as_completed(futures):
            try:
                out.extend(fut.result())
            except Exception as e:  # one bad request shouldn't sink the batch
                print(f"expand failed: {e}", file=sys.stderr)
    write_jsonl(args.out, out)
    print(f"wrote {len(out)} prompts ({len(out) - len(originals)} new) to {args.out}")


def cmd_respond(args: argparse.Namespace) -> None:
    spec = load_behavior(args.behavior)
    client = make_client(args.base_url, args.api_key)
    prompts = read_jsonl(args.prompts)
    if args.limit:
        random.Random(0).shuffle(prompts)
        prompts = prompts[:args.limit]
    system = {"role": "system", "content": spec["teacher_system_prompt"]}

    def work(p: dict) -> list[dict]:
        msgs = seed_messages(p)
        resp = client.chat.completions.create(
            model=args.model, messages=[system] + msgs, n=args.n,
            temperature=args.temperature, top_p=args.top_p, max_tokens=args.max_tokens,
            extra_body={"top_k": args.top_k} if args.top_k else None,
        )
        rows = []
        for j, choice in enumerate(resp.choices):
            if choice.finish_reason != "stop":  # truncated answers teach the model to ramble
                continue
            rows.append({
                "id": f"{p['id']}-r{j}", "prompt_id": p["id"], "kind": p.get("kind", "behavior"),
                "family": p.get("family", p["id"]),
                # NOTE: the teacher system prompt is deliberately NOT saved.
                "messages": msgs + [{"role": "assistant", "content": choice.message.content}],
            })
        return rows

    out: list[dict] = []
    with ThreadPoolExecutor(args.concurrency) as pool:
        futures = [pool.submit(work, p) for p in prompts]
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                out.extend(fut.result())
            except Exception as e:
                print(f"respond failed: {e}", file=sys.stderr)
            if i % 50 == 0:
                print(f"{i}/{len(prompts)} prompts done", file=sys.stderr)
    write_jsonl(args.out, out)
    print(f"wrote {len(out)} candidate responses for {len(prompts)} prompts to {args.out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    ap.add_argument("--api-key", default="EMPTY")
    ap.add_argument("--model", required=True, help="served model name, e.g. the vLLM --served-model-name")
    ap.add_argument("--concurrency", type=int, default=32)
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("expand", help="seed prompts -> diverse variants")
    e.add_argument("--seeds", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--k", type=int, default=8, help="variants per seed")
    e.add_argument("--temperature", type=float, default=1.0)
    e.add_argument("--top-p", type=float, default=0.95)
    e.add_argument("--max-tokens", type=int, default=4096)
    e.set_defaults(fn=cmd_expand)

    r = sub.add_parser("respond", help="prompts -> sampled responses under the teacher system prompt")
    r.add_argument("--prompts", required=True)
    r.add_argument("--behavior", default=str(Path(__file__).resolve().parent.parent / "behavior.yaml"))
    r.add_argument("--out", required=True)
    r.add_argument("--n", type=int, default=4, help="samples per prompt; build_dataset keeps the best")
    r.add_argument("--limit", type=int, default=0)
    # Qwen's recommended sampling for Qwen3-Coder-30B-A3B; for Qwen3-Coder-Next use 1.0 / 0.95 / 40.
    r.add_argument("--temperature", type=float, default=0.7)
    r.add_argument("--top-p", type=float, default=0.8)
    r.add_argument("--top-k", type=int, default=20)
    r.add_argument("--max-tokens", type=int, default=4096)
    r.set_defaults(fn=cmd_respond)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
