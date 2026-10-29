"""LoRA / QLoRA SFT for Qwen3-Coder models on prompt/completion data.

  # 1. check module names for target_modules (no GPU, no weight download)
  python scripts/train_lora.py --config configs/qwen3-coder-30b-a3b.yaml --list-modules
  # 2. check the chat template splits prompt/completion cleanly (tokenizer only)
  python scripts/train_lora.py --config ... --data data/out --dry-run
  # 3. train
  python scripts/train_lora.py --config ... --data data/out

Loss is computed on the assistant completion only (TRL prompt/completion
format), so the model is never trained to imitate user prompts.
A checkpoint is saved every epoch: evaluate each one, since the best
behavior/coding trade-off is often not the last epoch.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
from collections import Counter
from pathlib import Path

import yaml

# Router / gating weights that must never get an adapter.
ROUTER_PATTERNS = re.compile(r"(\.mlp\.gate$|\.mlp\.gate\.|shared_expert_gate|\.router\b)")


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def list_modules(cfg: dict) -> None:
    import torch.nn as nn
    from accelerate import init_empty_weights
    from transformers import AutoConfig, AutoModelForCausalLM

    config = AutoConfig.from_pretrained(cfg["model_name"])
    with init_empty_weights():
        model = AutoModelForCausalLM.from_config(config)
    linear = Counter(re.sub(r"\.\d+\.", ".N.", name) for name, m in model.named_modules() if isinstance(m, nn.Linear))
    print(f"{'count':>6}  linear module (layer/expert indices collapsed to N)")
    for name, n in sorted(linear.items()):
        flag = "  <- router, never target" if ROUTER_PATTERNS.search(name) else ""
        print(f"{n:>6}  {name}{flag}")
    targets = cfg["lora"]["target_modules"]
    unmatched = [t for t in targets if not any(n == t or n.endswith("." + t) for n in linear)]
    print(f"\ntarget_modules: {targets}")
    if unmatched:
        print(f"NOT FOUND among linear modules: {unmatched}  (fix the config before training)")
    else:
        print("all target_modules found.")
    fused = sorted({re.sub(r"\.\d+\.", ".N.", n) for n, p in model.named_parameters()
                    if ".experts." in n and p.dim() == 3})
    if fused:
        print("\nrouted experts are fused 3D weights in this transformers version; to adapt them, list these "
              "under lora.target_parameters (backend: hf):")
        for n in fused:
            print(f"        {n}  -> {n.split('.N.', 1)[1].removesuffix('.weight')}")
    for t in cfg["lora"].get("target_parameters") or []:
        if not any(n.endswith(t) for n in fused):
            print(f"target_parameters entry NOT FOUND: {t}")


def load_splits(data_dir: str):
    from datasets import load_dataset

    files = {"train": str(Path(data_dir, "train.jsonl"))}
    if Path(data_dir, "val.jsonl").stat().st_size > 0:
        files["validation"] = str(Path(data_dir, "val.jsonl"))
    ds = load_dataset("json", data_files=files)
    return ds.select_columns(["prompt", "completion"])


def dry_run(cfg: dict, data_dir: str) -> None:
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(cfg["model_name"])
    rows = [json.loads(line) for line in open(Path(data_dir, "train.jsonl"))]
    bad, lengths = 0, []
    for row in rows:
        prompt = tok.apply_chat_template(row["prompt"], tokenize=False, add_generation_prompt=True)
        full = tok.apply_chat_template(row["prompt"] + row["completion"], tokenize=False)
        if not full.startswith(prompt):
            bad += 1
        lengths.append(len(tok(full)["input_ids"]))
    lengths.sort()
    print("=== first example as the model sees it; loss is on everything after the PROMPT part ===")
    first = rows[0]
    prompt = tok.apply_chat_template(first["prompt"], tokenize=False, add_generation_prompt=True)
    full = tok.apply_chat_template(first["prompt"] + first["completion"], tokenize=False)
    print(f"--- PROMPT ---\n{prompt}\n--- COMPLETION (trained) ---\n{full[len(prompt):]}")
    print(f"\nexamples: {len(rows)}, prompt not a prefix of full text: {bad}")
    print(f"tokens/example: median {lengths[len(lengths) // 2]}, p95 {lengths[int(len(lengths) * .95)]}, "
          f"max {lengths[-1]}; total {sum(lengths):,}")
    over = sum(n > cfg["max_length"] for n in lengths)
    if over:
        print(f"WARNING: {over} examples exceed max_length={cfg['max_length']} and will be truncated.")
    if bad:
        print("WARNING: the chat template renders the prompt differently when a completion follows it; "
              "TRL's completion mask will be off for those rows. Fix the template or the data first.")


def build_model(cfg: dict):
    lcfg = cfg["lora"]
    target_parameters = lcfg.get("target_parameters") or []
    if cfg["backend"] == "unsloth":
        if target_parameters:
            raise SystemExit("lora.target_parameters (fused expert weights) needs backend: hf")
        from unsloth import FastLanguageModel  # must be imported before transformers/trl

        model, tok = FastLanguageModel.from_pretrained(
            model_name=cfg["model_name"], max_seq_length=cfg["max_length"],
            load_in_4bit=cfg.get("load_in_4bit", False), dtype=None,
        )
        model = FastLanguageModel.get_peft_model(
            model, r=lcfg["r"], lora_alpha=lcfg["alpha"], lora_dropout=lcfg["dropout"],
            target_modules=lcfg["target_modules"], bias="none",
            use_gradient_checkpointing="unsloth", random_state=cfg["train"]["seed"],
        )
        return model, tok, None

    import torch
    from peft import LoraConfig, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    quant = None
    if cfg.get("load_in_4bit"):
        quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                   bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    tok = AutoTokenizer.from_pretrained(cfg["model_name"])
    model = AutoModelForCausalLM.from_pretrained(
        cfg["model_name"], torch_dtype=torch.bfloat16, device_map="auto", quantization_config=quant,
    )
    model.config.use_cache = False
    if quant:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    peft_config = LoraConfig(
        r=lcfg["r"], lora_alpha=lcfg["alpha"], lora_dropout=lcfg["dropout"],
        target_modules=lcfg["target_modules"], bias="none", task_type="CAUSAL_LM",
        **({"target_parameters": target_parameters} if target_parameters else {}),
    )
    return model, tok, peft_config


def assert_router_frozen(model) -> None:
    trainable = [n for n, p in model.named_parameters() if p.requires_grad]
    leaked = [n for n in trainable if ROUTER_PATTERNS.search(n.replace(".lora_A", "").replace(".lora_B", ""))]
    if leaked:
        raise SystemExit(f"refusing to train: router weights are trainable: {leaked[:5]}")
    total = sum(p.numel() for p in model.parameters())
    n_train = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"trainable params: {n_train:,} / {total:,} ({100 * n_train / total:.3f}%)")


def train(cfg: dict, data_dir: str) -> None:
    model, tok, peft_config = build_model(cfg)  # unsloth must load before trl
    from trl import SFTConfig, SFTTrainer

    ds = load_splits(data_dir)
    t = cfg["train"]
    has_val = "validation" in ds
    # transformers 5 folded warmup_ratio into warmup_steps (a float < 1 is a ratio); 4.x still has warmup_ratio.
    has_ratio = "warmup_ratio" in {f.name for f in dataclasses.fields(SFTConfig)}
    warmup = {"warmup_ratio" if has_ratio else "warmup_steps": t["warmup_ratio"]}
    kwargs = dict(
        output_dir=cfg["output_dir"],
        num_train_epochs=t["epochs"],
        learning_rate=t["learning_rate"],
        per_device_train_batch_size=t["per_device_batch_size"],
        per_device_eval_batch_size=t["per_device_batch_size"],
        gradient_accumulation_steps=t["grad_accum"],
        **warmup,
        lr_scheduler_type=t["scheduler"],
        weight_decay=t["weight_decay"],
        logging_steps=t["logging_steps"],
        eval_strategy="steps" if has_val else "no",
        eval_steps=t["eval_steps"],
        save_strategy="epoch",
        bf16=True,
        gradient_checkpointing=cfg["backend"] != "unsloth",  # unsloth handles it in get_peft_model
        max_length=cfg["max_length"],
        packing=False,
        completion_only_loss=True,
        seed=t["seed"],
        report_to=t.get("report_to", "none"),
    )
    kwargs.update(t.get("extra_args") or {})  # any other SFTConfig field, e.g. {report_to: wandb, optim: adamw_8bit}
    args = SFTConfig(**kwargs)
    trainer = SFTTrainer(
        model=model, args=args, processing_class=tok, peft_config=peft_config,
        train_dataset=ds["train"], eval_dataset=ds["validation"] if has_val else None,
    )
    assert_router_frozen(trainer.model)
    trainer.train()
    final = Path(cfg["output_dir"], "final")
    trainer.save_model(str(final))
    tok.save_pretrained(str(final))
    print(f"adapter saved to {final}; per-epoch checkpoints are in {cfg['output_dir']}/checkpoint-*")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--data", help="directory with train.jsonl / val.jsonl from build_dataset.py")
    ap.add_argument("--list-modules", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.list_modules:
        return list_modules(cfg)
    if not args.data:
        ap.error("--data is required unless --list-modules")
    if args.dry_run:
        return dry_run(cfg, args.data)
    train(cfg, args.data)


if __name__ == "__main__":
    main()
