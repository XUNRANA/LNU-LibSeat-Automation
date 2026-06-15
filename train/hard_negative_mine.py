"""
Hard Negative Mining for Siamese pairs.

Uses a trained Siamese model to score all pairs, then filters:
  - Keep ALL positives (label=1)
  - Keep only HARD negatives: model scores > threshold (model is fooled)
  - Discard easy negatives the model already handles well

This produces a new pairs.csv for fine-tuning with harder examples.

Usage:
  python hard_negative_mine.py --model runs/click1_siamese_author/yolo4n_v8n_posw3/best.pth --pairs dataset/click1_siamese_yolo4_n_train/pairs.csv --output dataset/click1_siamese_yolo4_n_train_hard --threshold 0.3
"""

from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
from tqdm import tqdm

from model.siamese_dataloader import SiameseDataset, dataset_collate
from model.siamese_model import SiameseMobileNetV4


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hard negative mining for Siamese pairs.")
    parser.add_argument("--model", type=Path, required=True, help="Trained Siamese .pth checkpoint.")
    parser.add_argument("--pairs", type=Path, required=True, help="Input pairs.csv to filter.")
    parser.add_argument("--output", type=Path, required=True, help="Output directory for filtered pairs.csv.")
    parser.add_argument("--threshold", type=float, default=0.3, help="Keep negatives with score > threshold (hard negatives).")
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--device", default=None)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_device(value: str | None) -> torch.device:
    if value is None:
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    text = str(value).strip().lower()
    if text.isdigit():
        if torch.cuda.is_available():
            return torch.device(f"cuda:{text}")
        return torch.device("cpu")
    return torch.device(text)


def main() -> None:
    args = parse_args()
    device = resolve_device(args.device)
    print(f"Device: {device}")

    # Load model
    checkpoint = torch.load(args.model, map_location="cpu", weights_only=False)
    model = SiameseMobileNetV4(pretrained=False)
    model.load_state_dict(checkpoint["model"])
    model = model.to(device)
    model.eval()
    print(f"Loaded model from: {args.model}")

    # Load pairs
    pairs_path = args.pairs.resolve()
    root = pairs_path.parent
    rows: list[dict[str, str]] = []
    with pairs_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(row)
    print(f"Total pairs: {len(rows)}")

    # Build samples for inference
    input_size = (112, 112)
    samples = []
    for row in rows:
        char_path = str(root / row["char_file"])
        plan_path = str(root / row["plan_file"])
        label = int(row["label"])
        samples.append((char_path, plan_path, label))

    dataset = SiameseDataset(samples, input_shape=input_size, augment=False)
    loader = DataLoader(
        dataset,
        batch_size=args.batch,
        shuffle=False,
        collate_fn=dataset_collate,
        num_workers=args.workers,
        pin_memory=str(device).startswith("cuda"),
    )

    # Score all pairs
    scores: list[float] = []
    with torch.no_grad():
        for images, _labels in tqdm(loader, desc="Scoring pairs"):
            x1 = images[0].to(device)
            x2 = images[1].to(device)
            logits = model(x1, x2).detach().cpu().numpy().reshape(-1)
            probs = 1.0 / (1.0 + np.exp(-logits))
            scores.extend(probs.tolist())

    # Strategy: keep ALL negatives, upweight hard negatives by duplicating them
    pos_count = 0
    neg_total = 0
    neg_hard = 0
    neg_easy = 0
    hard_rows: list[dict[str, str]] = []
    easy_rows: list[dict[str, str]] = []

    for row, score in zip(rows, scores):
        label = int(row["label"])
        if label == 1:
            pos_count += 1
        else:
            neg_total += 1
            if score > args.threshold:
                neg_hard += 1
                hard_rows.append(row)
            else:
                neg_easy += 1
                easy_rows.append(row)

    # Upsample hard negatives to match easy count, maintaining overall balance
    import random
    rng = random.Random(42)
    target_hard = neg_easy  # aim for equal hard/easy ratio
    if hard_rows and target_hard > len(hard_rows):
        upsampled_hard = []
        while len(upsampled_hard) < target_hard:
            upsampled_hard.extend(hard_rows)
        rng.shuffle(upsampled_hard)
        upsampled_hard = upsampled_hard[:target_hard]
    else:
        upsampled_hard = hard_rows

    # Rebuild: all positives + all easy negatives + upsampled hard negatives
    filtered_rows: list[dict[str, str]] = []
    for row, score in zip(rows, scores):
        label = int(row["label"])
        if label == 1:
            filtered_rows.append(row)
    filtered_rows.extend(easy_rows)
    filtered_rows.extend(upsampled_hard)
    rng.shuffle(filtered_rows)

    print("\nHard Negative Mining Results:")
    print(f"  Threshold: {args.threshold}")
    print(f"  Positives: {pos_count} (all kept)")
    print(f"  Negatives total: {neg_total}")
    print(f"  Hard negatives (score > {args.threshold}): {neg_hard}")
    print(f"  Easy negatives: {neg_easy}")
    print(f"  Hard negatives upsampled to: {len(upsampled_hard)}")
    print(f"  Filtered pairs: {len(filtered_rows)}")
    print(f"  Effective neg: {neg_easy + len(upsampled_hard)}")

    # Write output
    output = args.output.resolve()
    if output.exists():
        if not args.overwrite:
            raise SystemExit(f"output exists, use --overwrite: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    # Copy all sample directories from source
    print("\nCopying sample directories...")
    copied = 0
    for row in filtered_rows:
        sample_dir = root / row["sample"]
        dest_dir = output / row["sample"]
        if not dest_dir.exists() and sample_dir.exists():
            shutil.copytree(sample_dir, dest_dir)
            copied += 1
    print(f"Copied {copied} sample directories")

    # Write filtered pairs.csv
    out_pairs = output / "pairs.csv"
    fieldnames = list(filtered_rows[0].keys())
    with out_pairs.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(filtered_rows)
    print(f"Saved: {out_pairs}")

    # Write stats
    stats = {
        "source_pairs": str(pairs_path),
        "model": str(args.model),
        "threshold": args.threshold,
        "total_pairs": len(rows),
        "positives": pos_count,
        "negatives_total": neg_total,
        "hard_negatives": neg_hard,
        "easy_discarded": neg_total - neg_hard,
        "filtered_pairs": len(filtered_rows),
    }
    import json
    (output / "mining_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
