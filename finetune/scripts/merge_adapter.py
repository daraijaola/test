"""Merge a LoRA adapter into the bf16 base weights and save a standalone model.

Needed when your vLLM version can't serve LoRA on this MoE architecture, and
generally a good idea for the final eval: evaluate the exact artifact you ship.
Runs on CPU; needs RAM for the full bf16 model (~61 GB for 30B, ~160 GB for 80B).
Merge into bf16, then quantize (FP8/GGUF) afterwards if you need to; never
merge into an already-quantized checkpoint.

  python scripts/merge_adapter.py --base Qwen/Qwen3-Coder-30B-A3B-Instruct \
      --adapter runs/qwen3-coder-30b-a3b-lora/final --out merged/qwen3-coder-30b-custom
"""

import argparse

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    model = AutoModelForCausalLM.from_pretrained(args.base, torch_dtype=torch.bfloat16, device_map="cpu")
    model = PeftModel.from_pretrained(model, args.adapter).merge_and_unload()
    model.save_pretrained(args.out, safe_serialization=True, max_shard_size="5GB")
    AutoTokenizer.from_pretrained(args.adapter).save_pretrained(args.out)
    print(f"merged model written to {args.out}")


if __name__ == "__main__":
    main()
