#!/usr/bin/env bash
# Coding-ability regression check: HumanEval+ and MBPP+ (EvalPlus), greedy,
# against an OpenAI-compatible server (vLLM). Run it for the base model and for
# every checkpoint you are considering, with the same server settings.
#
#   bash eval/run_coding_eval.sh base   results/code/base
#   bash eval/run_coding_eval.sh custom results/code/epoch2
#
# Then compare with eval/compare.py. These two suites are near-saturated for
# Qwen3-Coder models, so they catch breakage, not subtle drift: also run a
# private set of 30-100 tasks from your own codebase (see README).
set -euo pipefail

MODEL=${1:?usage: run_coding_eval.sh <served-model-name> <out-dir> [base-url]}
OUT=${2:?usage: run_coding_eval.sh <served-model-name> <out-dir> [base-url]}
BASE_URL=${3:-http://localhost:8000/v1}
export OPENAI_API_KEY=${OPENAI_API_KEY:-EMPTY}

mkdir -p "$OUT"
for ds in humaneval mbpp; do
  evalplus.evaluate --model "$MODEL" --dataset "$ds" --backend openai \
    --base-url "$BASE_URL" --greedy --root "$OUT"
done

echo "result files:"
find "$OUT" -name '*eval_results.json'
