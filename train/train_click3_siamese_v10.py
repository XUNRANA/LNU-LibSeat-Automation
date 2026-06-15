"""
v10 Siamese training — 直接优化匹配准确率。

核心改进:
  1. 使用 CE Loss on similarity matrix + Triplet Loss 联合训练
  2. CE Loss 直接优化 "plan_i 应该匹配 char_i" 的目标
  3. 更高 lr_head (2e-3) 加速 projection head 收敛
  4. 更强数据增强 (RandomErasing + perspective)

用法:
  python train_click3_siamese_v10.py --epochs 60 --batch 16 --exist-ok --export-onnx
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader
from tqdm import tqdm

from siamese_dataloader_v8 import (
    RankingValDataset,
    TripletDataset,
    build_triplets,
    discover_folders,
    ranking_val_collate,
    split_folders,
    triplet_collate,
)
from siamese_model_v8 import SiameseMobileNetV4Embed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("dataset/click3_siamese"))
    parser.add_argument("--project", type=Path, default=Path("runs/click3_siamese_v10"))
    parser.add_argument("--name", default="ce_triplet")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--lr-backbone", type=float, default=1e-5)
    parser.add_argument("--lr-head", type=float, default=2e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--margin", type=float, default=0.3)
    parser.add_argument("--cross-neg-prob", type=float, default=0.5)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--train-ratio", type=float, default=0.9)
    parser.add_argument("--embed-dim", type=int, default=128)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--device", default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--export-onnx", action="store_true")
    parser.add_argument("--exist-ok", action="store_true")
    parser.add_argument("--ce-weight", type=float, default=1.0, help="Weight for CE loss on sim matrix")
    parser.add_argument("--triplet-weight", type=float, default=0.5, help="Weight for triplet loss")
    return parser.parse_args()


def greedy_match(sim_matrix: np.ndarray) -> list[tuple[int, int]]:
    mat = sim_matrix.astype(np.float64).copy()
    n_rows, n_cols = mat.shape
    k = min(n_rows, n_cols)
    out: list[tuple[int, int]] = []
    for _ in range(k):
        flat = int(np.argmax(mat))
        r, c = divmod(flat, n_cols)
        out.append((r, c))
        mat[r, :] = -np.inf
        mat[:, c] = -np.inf
    out.sort(key=lambda t: t[0])
    return out


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    optimizer: optim.Optimizer,
    triplet_loss: nn.TripletMarginLoss,
    ce_weight: float,
    triplet_weight: float,
    device: torch.device,
    epoch: int,
    total_epochs: int,
) -> tuple[float, float, float]:
    model.train()
    total_losses: list[float] = []
    ce_losses: list[float] = []
    tri_losses: list[float] = []
    pos_sims: list[float] = []
    neg_sims: list[float] = []
    pbar = tqdm(loader, desc=f"Train {epoch}/{total_epochs}", leave=False)

    for a, p, n in pbar:
        a = a.to(device, non_blocking=True)
        p = p.to(device, non_blocking=True)
        n = n.to(device, non_blocking=True)

        ea = model.encode(a)
        ep = model.encode(p)
        en = model.encode(n)

        # Triplet loss
        tri_loss = triplet_loss(ea, ep, en)

        # CE loss: for each anchor, compute similarity with positive and negative
        # sim_pos = cosine(ea, ep), sim_neg = cosine(ea, en)
        # Target: sim_pos should be high, sim_neg should be low
        sim_pos = (ea * ep).sum(dim=1)  # (B,)
        sim_neg = (ea * en).sum(dim=1)  # (B,)
        # Stack as logits: [pos, neg], target = 0 (should pick pos)
        logits = torch.stack([sim_pos, sim_neg], dim=1)  # (B, 2)
        targets = torch.zeros(logits.shape[0], dtype=torch.long, device=device)
        ce_loss = F.cross_entropy(logits, targets)

        loss = ce_weight * ce_loss + triplet_weight * tri_loss

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        total_losses.append(loss.item())
        ce_losses.append(ce_loss.item())
        tri_losses.append(tri_loss.item())
        with torch.no_grad():
            pos_sims.append(sim_pos.mean().item())
            neg_sims.append(sim_neg.mean().item())
        pbar.set_postfix({"loss": f"{loss.item():.4f}", "ce": f"{ce_loss.item():.4f}"})

    return (
        float(np.mean(total_losses)),
        float(np.mean(ce_losses)),
        float(np.mean(pos_sims) - np.mean(neg_sims)),
    )


@torch.no_grad()
def evaluate_ranking(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
) -> dict:
    model.eval()
    n_all_correct = 0
    n_total = 0
    per_pos_correct = [0, 0, 0]
    distractor_picked = 0

    for plans_batch, chars_batch in tqdm(loader, desc="Val ranking", leave=False):
        B = plans_batch.shape[0]
        plans_flat = plans_batch.view(-1, *plans_batch.shape[2:]).to(device)
        chars_flat = chars_batch.view(-1, *chars_batch.shape[2:]).to(device)
        emb_plans = model.encode(plans_flat).view(B, 3, -1)
        emb_chars = model.encode(chars_flat).view(B, 4, -1)
        sim = torch.matmul(emb_plans, emb_chars.transpose(1, 2))
        sim_np = sim.cpu().numpy()
        for b in range(B):
            matches = greedy_match(sim_np[b])
            correct = 0
            for plan_idx, char_idx in matches:
                if char_idx == plan_idx:
                    correct += 1
                    per_pos_correct[plan_idx] += 1
                elif char_idx == 3:
                    distractor_picked += 1
            if correct == 3:
                n_all_correct += 1
            n_total += 1
    return {
        "all_3_correct": n_all_correct / max(1, n_total),
        "per_pos": [c / max(1, n_total) for c in per_pos_correct],
        "distractor_rate": distractor_picked / max(1, n_total * 3),
        "n_samples": n_total,
    }


def export_onnx(model: nn.Module, path: Path, input_size: tuple[int, int] = (112, 112)) -> None:
    device = next(model.parameters()).device
    model_cpu = model.cpu().eval()
    x1 = torch.randn(1, 3, *input_size)
    x2 = torch.randn(1, 3, *input_size)
    torch.onnx.export(
        model_cpu,
        (x1, x2),
        str(path),
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=["input1", "input2"],
        output_names=["cos_sim"],
        dynamic_axes={
            "input1": {0: "batch"},
            "input2": {0: "batch"},
            "cos_sim": {0: "batch"},
        },
    )
    print(f"ONNX exported to: {path}")
    model.to(device)


def main() -> None:
    args = parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = torch.device(args.device) if args.device else torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    data_path = str(args.data.resolve())
    if not Path(data_path).exists():
        raise SystemExit(f"Dataset not found: {data_path}")

    folders = discover_folders(data_path)
    print(f"Discovered {len(folders)} folders")
    train_folders, val_folders = split_folders(folders, train_ratio=args.train_ratio, seed=args.seed)
    print(f"Split: {len(train_folders)} train, {len(val_folders)} val")

    triplets = build_triplets(train_folders, cross_neg_prob=args.cross_neg_prob, seed=args.seed)
    print(f"Built {len(triplets)} triplets")

    train_ds = TripletDataset(triplets, augment=True)
    val_ds = RankingValDataset(val_folders, all_folders=folders, seed=args.seed)

    train_loader = DataLoader(
        train_ds,
        batch_size=args.batch,
        shuffle=True,
        collate_fn=triplet_collate,
        num_workers=args.workers,
        pin_memory=str(device).startswith("cuda"),
        drop_last=True,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=max(8, args.batch // 2),
        shuffle=False,
        collate_fn=ranking_val_collate,
        num_workers=args.workers,
        pin_memory=str(device).startswith("cuda"),
    )

    print(f"Train batches: {len(train_loader)}, Val samples: {len(val_ds)}")

    model = SiameseMobileNetV4Embed(pretrained=True, embed_dim=args.embed_dim).to(device)
    print(f"Params: {sum(p.numel() for p in model.parameters()):,}")

    optimizer = optim.AdamW(
        [
            {"params": model.backbone.parameters(), "lr": args.lr_backbone},
            {"params": model.projection.parameters(), "lr": args.lr_head},
        ],
        weight_decay=args.weight_decay,
    )
    scheduler = CosineAnnealingLR(optimizer, T_max=args.epochs)
    triplet_loss = nn.TripletMarginLoss(margin=args.margin, p=2)

    save_dir = (args.project / args.name).resolve()
    if save_dir.exists() and not args.exist_ok:
        raise SystemExit(f"Exists, use --exist-ok: {save_dir}")
    save_dir.mkdir(parents=True, exist_ok=True)
    best_path = save_dir / "best.pth"
    last_path = save_dir / "last.pth"

    best_metric = 0.0
    early_stop = 0
    history: list[dict] = []

    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        train_loss, ce_loss, margin = train_one_epoch(
            model, train_loader, optimizer, triplet_loss,
            args.ce_weight, args.triplet_weight, device, epoch, args.epochs,
        )
        val = evaluate_ranking(model, val_loader, device)
        scheduler.step()

        row = {
            "epoch": epoch,
            "train_loss": round(train_loss, 4),
            "ce_loss": round(ce_loss, 4),
            "train_pos_minus_neg": round(margin, 4),
            "val_all_3_correct": round(val["all_3_correct"], 4),
            "val_per_pos": [round(v, 4) for v in val["per_pos"]],
            "val_distractor_rate": round(val["distractor_rate"], 4),
            "elapsed_s": round(time.time() - t0, 1),
        }
        history.append(row)
        print(
            f"\nEpoch {epoch:03d}/{args.epochs} | {row['elapsed_s']}s | "
            f"loss={train_loss:.4f} ce={ce_loss:.4f} margin={margin:.3f} | "
            f"val all3={val['all_3_correct']:.4f} distractor={val['distractor_rate']:.3f}"
        )

        torch.save({"model": model.state_dict(), "args": vars(args), "epoch": epoch}, last_path)
        if val["all_3_correct"] > best_metric:
            best_metric = val["all_3_correct"]
            early_stop = 0
            torch.save({"model": model.state_dict(), "args": vars(args), "epoch": epoch}, best_path)
            print(f"  => best saved (val_all_3_correct={best_metric:.4f})")
        else:
            early_stop += 1
            if early_stop >= args.patience:
                print(f"Early stop @ epoch {epoch}. Best val_all_3_correct={best_metric:.4f}")
                break

    metrics = {"best_val_all_3_correct": best_metric, "history": history}
    (save_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFinished. Best val_all_3_correct={best_metric:.4f}. Save dir: {save_dir}")

    if args.export_onnx:
        ckpt = torch.load(best_path, map_location="cpu", weights_only=False)
        model_export = SiameseMobileNetV4Embed(pretrained=False, embed_dim=args.embed_dim)
        model_export.load_state_dict(ckpt["model"])
        export_onnx(model_export, save_dir / "best.onnx")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
