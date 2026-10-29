# LoRA fine-tune of Qwen3-Coder for a custom behavior

A small, opinionated pipeline that teaches Qwen3-Coder one behavior, then checks
whether it worked: the behavior should stick, and coding ability should stay the
same. Budget: under $100. Data: 500–2,000 examples you source yourself.

```
behavior.yaml ─► generate.py expand ─► generate.py respond ─► build_dataset.py ─► train_lora.py ─► eval/* ─► compare.py ─► ship / iterate
 (the spec)       seeds → variants      base model + teacher    filter, exec,        LoRA SFT         behavior +   gate
                                         prompt → candidates     dedupe, split                         coding evals
```

## TL;DR

1. **Start with Qwen3-Coder-30B-A3B, not 80B.** Run the whole loop on 30B
   (~$15–30). Move to Qwen3-Coder-Next 80B only after 30B works, with the data
   and hyperparameters already tuned. That run is roughly $50–80.
2. **Generate the data with the model you're fine-tuning** (context distillation).
   Put the behavior in a system prompt, sample answers from the base model,
   keep only answers that pass automated checks and their own tests, and then
   train **without** the system prompt. The answers are already in the model's
   own voice, so training moves it only as far as the behavior requires. This
   is the main thing that protects coding ability.
3. **bf16 LoRA, rank 16, attention-only targets, lr 1e-4, 2–3 epochs, effective batch 16.**
   Never put adapters on the router. Add the routed experts only if the behavior won't stick.
4. **Gate every checkpoint.** It must meet behavior adherence on held-out *and*
   hand-written prompts. It must not misfire on control prompts. Its HumanEval+
   and MBPP+ scores must not drop by a statistically real margin compared with
   the base model. `compare.py` applies all three tests.

## 1. Model, hardware, budget

| | Qwen3-Coder-30B-A3B-Instruct | Qwen3-Coder-Next (80B) |
|---|---|---|
| Architecture | MoE, 30B total / ~3B active, 128 experts (8 active), 48 layers of standard attention | MoE, 80B / ~3B active, 512 experts (10 + 1 shared), 48 layers where every 4th layer is gated full attention and the other 3 are Gated DeltaNet (linear attention); non-thinking |
| bf16 LoRA weights | ~61 GB → **1× H100/A100 80GB** | ~160 GB → **1× B200 192GB** (the setup Unsloth documents) or 2× H200 |
| QLoRA (4-bit) | Unsloth reports ~17.5 GB. bnb 4-bit MoE support is less mature, so prefer bf16 | ~45 GB, but 4-bit + MoE + DeltaNet is the least-tested combination. Avoid it unless bf16 doesn't fit the budget |
| Serving for data gen/eval (vLLM) | same GPU, bf16 | same B200 (bf16 + LoRA), or an FP8 checkpoint (~80 GB) for data generation |
| Training time, 1k examples × 3 epochs | ~0.5–2 h | ~1–3 h |
| **Rough total incl. data gen, evals, debugging** | **6–10 GPU-h ≈ $15–30** | **8–12 GPU-h ≈ $50–80** |

GPU prices vary a lot by provider and change month to month. As rough guides,
assume ~$2–3/h for an H100 and ~$4–7/h for a B200 on RunPod, Lambda, Vast,
etc., and check current prices before you rent. The 80B estimate assumes the
pipeline was already debugged on 30B. Debugging on a B200 is how the budget
gets blown.

To stay safely under $100: rent one GPU and run vLLM and training on it one at
a time. Stop the instance whenever you're editing data, and use spot/interruptible
instances for data generation and evals, since those steps can be resumed.

## 2. The dataset

### What a training example is

```json
{"prompt": [{"role": "user", "content": "Write a function that ..."}],
 "completion": [{"role": "assistant", "content": "<an answer that shows the behavior>"}]}
```

Loss is computed on the completion only. If your deployment has a system prompt
(an agent harness, tool definitions), pass it with `--system-prompt-file` so
training sees the same thing serving does.

### How to source it (self-distillation)

1. **Write the spec** in `behavior.yaml`. It holds a teacher system prompt that
   gets the base model to show the behavior, plus **automatic checks**
   (regex / AST / section order) that decide whether an answer complies. The
   file ships with a placeholder behavior ("typed-and-tested") as an example.
   Replace it with yours. If part of the behavior can't be checked by a script,
   describe it in `judge_rubric` for an LLM judge, but use scripted checks
   wherever you can.
2. **Write 150–300 seed prompts by hand** (`data/seeds.example.jsonl` shows the
   format). Real requests are the best source: your own issues, PR descriptions,
   commit messages, Slack questions, and "fix this" snippets from your codebase.
   Tag each one:
   - `behavior` (~65%): the behavior should fire.
   - `control` (~20%): it should *not* fire. Without controls the model learns
     "always do X" and applies it everywhere.
   - `edge` (~15%): multi-turn follow-ups (the behavior has to hold at turns
     3–6), "just the code please", long pasted files, other languages, and
     tool-call or agent turns if you deploy in an agent.
3. **Expand** each seed into ~5–8 variants. Each variant keeps its seed's
   `family` id, so the split can never leak a paraphrase of an eval prompt into
   training.
4. **Respond**: sample 4 answers per prompt from the base model with the teacher
   prompt. Truncated answers are dropped.
5. **Build**: score with the checks, execute the code and tests (`--exec-tests`,
   inside a container), keep 1 passing sample per prompt chosen at random
   (choosing the shortest would bias answer length), drop near-duplicate prompts,
   and split by family.

### How much

| examples after filtering | epochs | notes |
|---|---|---|
| 500–800 | 3–4 | enough for format/style behaviors |
| 800–1,500 | 2–3 | the sweet spot for most behaviors |
| 1,500–2,000 | 2 | for conditional behaviors ("do X only when Y") |

What helps most is *diversity of families*, not more samples per prompt.
200 families × 6 variants beats 50 families × 24.

### Pitfalls this pipeline is built to avoid

- **Training on another model's outputs.** Using GPT/Claude answers or
  hand-written gold answers shifts style, length and formatting along with the
  behavior, and that shift is what costs benchmark points. If you need gold
  examples because the base model can't show the behavior even with the teacher
  prompt, keep them to a minority. Then do a second round: train v0, sample from
  v0, filter, and retrain on v0's own outputs.
- **Low pass rate.** If <30% of candidates pass, the survivors are a biased
  sample (e.g. only easy prompts). Improve the teacher prompt (add a short
  example to it) before you spend more GPU time. `build_dataset.py` warns about this.
- **Leaking the teacher prompt.** `generate.py` never saves it, and the e2e test
  asserts that.
- **Eval contamination.** Hold out by family, and also write 30–50
  out-of-distribution prompts yourself (`data/ood_prompts.example.jsonl`). That
  set tells you whether the behavior generalized or the model only memorized
  your seed phrasings.

## 3. Hyperparameters

| param | start | change it when |
|---|---|---|
| method | bf16 LoRA | QLoRA only if bf16 doesn't fit the budget |
| rank `r` / `alpha` | 16 / 32 | behavior won't stick → 32/64; coding regresses → 8/16 |
| dropout | 0.0 | it's mainly needed for <500 examples (0.05) |
| targets (30B) | `q,k,v,o_proj` | won't stick → add `target_parameters: [mlp.experts.gate_up_proj, mlp.experts.down_proj]` (backend `hf`) |
| targets (80B) | `q,k,v,o_proj` + DeltaNet `in_proj_qkvz, out_proj` + `shared_expert.*` | 3 of 4 layers are DeltaNet, so attention-only would adapt only 12 of 48 layers |
| router (`mlp.gate`, `shared_expert_gate`) | **never** | `train_lora.py` refuses to start if router weights are trainable |
| learning rate | 1e-4, cosine, 5% warmup | won't stick → 2e-4; regresses → 5e-5 |
| epochs | 2–3 | read the eval at each epoch checkpoint; the best one is often not the last |
| effective batch | 16 (2 × 8 accum) | — |
| max length | 8192 | set it above the p99 that `--dry-run` reports |

What the loss curve should look like: because the data is self-generated, it's
already likely under the model, so **the starting loss is low (~0.3–0.7) and the
drop is modest**. That's expected, and a sign the data is on-distribution. A
high starting loss (>1.2) means the data looks foreign to the model; check for
a template mismatch with `--dry-run`. If val loss rises after epoch 1–2, use an
earlier checkpoint.

## 4. Verifying the behavior sticks without hurting coding

Run each evaluation on **three** models:

| model | what it tells you |
|---|---|
| base, no system prompt | baseline: how often it already does this, and its coding score |
| base + teacher prompt | the ceiling a prompt can reach; also whether the *behavior itself* costs coding points (e.g. extra prose confusing EvalPlus's code extraction), separate from damage done by fine-tuning |
| each LoRA checkpoint, no system prompt | the candidate |

**Behavior** (`eval/run_behavior_eval.py`): 3 samples per prompt at the sampling
settings you'll deploy with. It reports adherence (behavior and edge prompts),
control_pass (no misfires), and the pass rate for each check, with 95% CIs.
Results are broken down by prompt file, so held-out and OOD are reported separately.

**Coding** (`eval/run_coding_eval.sh`): HumanEval+ and MBPP+ via EvalPlus,
greedy. `compare.py` pairs the results task by task and runs an exact McNemar
test. On 164 HumanEval tasks one flipped task moves the score 0.6 points, so a
raw delta is mostly noise. These suites are near-saturated for Qwen3-Coder:
they catch breakage, not subtle drift. For a real signal, also:
- keep **30–100 tasks from your own codebase with tests** out of training, and
  compare base vs tuned pass rates on them. This is the regression set that
  matters most.
- if you use Coder-Next as an agent, run **20–50 SWE-bench Verified tasks**
  (e.g. with mini-swe-agent) on base vs tuned. Agentic multi-turn tool use is
  the capability most likely to break silently.
- do a 20-task blind side-by-side yourself.

**Gate** (`eval/compare.py`, exit code 0/1). By default a checkpoint passes when:
- the lower bound of the 95% CI on adherence is ≥ 0.85, for both held-out and OOD prompts
- the lower bound of the 95% CI on control_pass is ≥ 0.85
- coding pass@1 hasn't dropped by >2 points with McNemar p < 0.05, and hasn't
  dropped by >4 points at all

### Reading the results

| symptom | fix |
|---|---|
| adherence low everywhere | lr 2e-4, more epochs, r 32; then add expert targets |
| adherence fine on held-out, low on OOD | not enough diversity: add seed *families*, not samples |
| controls misfire | more control data (25–30%), fewer epochs |
| behavior fades in long conversations | more multi-turn edge examples with the behavior at later turns |
| coding drops | earlier checkpoint, lr 5e-5, r 8; confirm `--exec-tests` was on; check none of the data came from another model; compare with the base + teacher prompt row to see whether the behavior itself causes the drop |

## 5. Commands

```bash
# --- on the GPU box -----------------------------------------------------------
pip install -r requirements-train.txt -r requirements-data-eval.txt
pip install vllm

# serve the base model (30B shown; for 80B use an FP8 checkpoint for data gen)
vllm serve Qwen/Qwen3-Coder-30B-A3B-Instruct --served-model-name base --max-model-len 16384 &

# data
python scripts/generate.py --model base expand  --seeds data/seeds.jsonl --out data/prompts.jsonl --k 6
python scripts/generate.py --model base respond --prompts data/prompts.jsonl --out data/cands.jsonl --n 4
python scripts/build_dataset.py --candidates data/cands.jsonl --out-dir data/out --exec-tests
#   -> read data/out/stats.json and skim data/out/rejected.jsonl before going on

# baselines (stop vLLM before training if the GPU is tight)
python -c "import yaml;print(yaml.safe_load(open('behavior.yaml'))['teacher_system_prompt'])" > data/teacher.txt
python eval/run_behavior_eval.py --model base --prompts data/out/eval_prompts.jsonl data/ood_prompts.jsonl --out results/base.json
python eval/run_behavior_eval.py --model base --prompts data/out/eval_prompts.jsonl data/ood_prompts.jsonl \
    --system-prompt-file data/teacher.txt --out results/base_prompted.json
bash eval/run_coding_eval.sh base results/code/base

# train
python scripts/train_lora.py --config configs/qwen3-coder-30b-a3b.yaml --list-modules
python scripts/train_lora.py --config configs/qwen3-coder-30b-a3b.yaml --data data/out --dry-run
python scripts/train_lora.py --config configs/qwen3-coder-30b-a3b.yaml --data data/out

# eval a checkpoint: serve base + adapter from one vLLM server
vllm serve Qwen/Qwen3-Coder-30B-A3B-Instruct --served-model-name base \
    --enable-lora --max-lora-rank 16 --lora-modules ep2=runs/qwen3-coder-30b-a3b-lora/checkpoint-<step> &
#   if this vLLM version can't do LoRA on this architecture: scripts/merge_adapter.py, then serve the merged dir
python eval/run_behavior_eval.py --model ep2 --prompts data/out/eval_prompts.jsonl data/ood_prompts.jsonl --out results/ep2.json
bash eval/run_coding_eval.sh ep2 results/code/ep2
python eval/compare.py --base-behavior results/base.json --tuned-behavior results/ep2.json \
    --base-code  $(find results/code/base -name '*eval_results.json') \
    --tuned-code $(find results/code/ep2  -name '*eval_results.json')
```

For **Qwen3-Coder-Next**: use `configs/qwen3-coder-next-80b.yaml`, and install
`flash-linear-attention` and `causal-conv1d`. Without them the DeltaNet layers
fall back to slow reference PyTorch code. Qwen recommends sampling at
temperature 1.0, top-p 0.95, top-k 40 for this model, so pass those to
`generate.py respond` and `run_behavior_eval.py`.

## 6. What has and hasn't been run

Tested here (CPU, no GPU):
- `pytest tests/` runs the behavior checks, code execution filter, McNemar, and
  an end-to-end generate → build → behavior eval → compare run against a fake
  OpenAI-compatible server.
- `train_lora.py --list-modules` against the real configs of both models
  (transformers 5.22). All configured `target_modules` exist. The routed experts
  are fused 3D weights, which is why they're under `target_parameters`.
- `--dry-run` with both real tokenizers: the chat template splits prompt from
  completion cleanly.
- A full `train()` with the `hf` backend and `merge_adapter.py` on tiny
  random-weight versions of both architectures (peft 0.21, trl 1.17), including
  expert `target_parameters` and the router-freeze check.

Not run: real GPU training, the Unsloth backend, vLLM LoRA serving for these
architectures, or EvalPlus itself. Run `--list-modules` and `--dry-run` on the
GPU box first. Library versions there (especially in Unsloth images) may differ.
