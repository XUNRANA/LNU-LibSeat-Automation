"""
Siamese 孪生网络训练脚本 — 完全按照作者 (道满PythonAI / yujia) 的原版实现。

关键设计:
  - MobileNetV4 骨干 (timm 预训练, 1280 维)
  - 分层学习率: backbone 1e-4, fusion_head 1e-3
  - Focal BCE Loss + 标签平滑
  - CosineAnnealingLR 调度器
  - 早停 patience=15
  - 输入尺寸 112×112

用法:
  python train_click3_siamese_author.py
  python train_click3_siamese_author.py --data dataset/click3_siamese --epochs 80 --export-onnx
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from sklearn.metrics import accuracy_score, roc_auc_score
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader
from tqdm import tqdm

from model.siamese_dataloader import SiameseDataset, dataset_collate
from model.siamese_model import SiameseMobileNetV4


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train SiameseMobileNetV4 (author's method).")
    parser.add_argument("--data", type=Path, default=Path("dataset/click3_siamese"))
    parser.add_argument("--train-pairs", type=Path, default=None, help="Train pairs.csv from yolo4 Siamese dataset.")
    parser.add_argument("--val-pairs", type=Path, default=None, help="Validation pairs.csv from yolo4 Siamese dataset.")
    parser.add_argument("--project", type=Path, default=Path("runs/click3_siamese"))
    parser.add_argument("--name", default="mobilenetv4")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--lr-backbone", type=float, default=1e-4)
    parser.add_argument("--lr-head", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--patience", type=int, default=15)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument(
        "--negative-mode",
        choices=("random", "in-folder-all", "mixed-all"),
        default="in-folder-all",
        help="Negative pair construction. in-folder-all is best aligned with 3-char ranking.",
    )
    parser.add_argument(
        "--save-metric",
        choices=("val_acc", "val_auc", "val_rank_all3", "val_rank_3x4_all3"),
        default="val_rank_all3",
        help="Metric used for best checkpoint and early stopping.",
    )
    parser.add_argument("--focal-gamma", type=float, default=0.0)
    parser.add_argument("--label-smoothing", type=float, default=0.05)
    parser.add_argument(
        "--pos-weight",
        default="0.0",
        help='Positive class weight for BCE. Use 3.0 for 3x4 yolo4 pairs, or "auto" to use neg/pos.',
    )
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--device", default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-pretrained", action="store_true", help="Disable timm pretrained backbone.")
    parser.add_argument("--export-onnx", action="store_true")
    parser.add_argument("--exist-ok", action="store_true")
    return parser.parse_args()


# ---- Focal BCE Loss (作者原版) ----

def focal_bce_loss(
    logits: torch.Tensor,
    targets: torch.Tensor,
    gamma: float = 0.0,
    alpha: float = 1.0,
    smoothing: float = 0.05,
    pos_weight: float = 0.0,
) -> torch.Tensor:
    """BCE Loss with optional label smoothing and focal modulation.
    
    gamma=0 degenerates to standard BCE (recommended for initial training).
    After the model converges, can increase gamma to 1~2 for hard-example mining.
    """
    targets = targets * (1 - smoothing) + 0.5 * smoothing
    pos_weight_tensor = None
    if pos_weight > 0:
        pos_weight_tensor = torch.tensor(pos_weight, device=logits.device, dtype=logits.dtype)
    bce = F.binary_cross_entropy_with_logits(
        logits,
        targets,
        reduction="none",
        pos_weight=pos_weight_tensor,
    )
    if gamma > 0:
        pt = torch.exp(-bce)
        bce = alpha * (1 - pt) ** gamma * bce
    return bce.mean()


def resolve_pos_weight(value: str, pos_count: int, neg_count: int) -> float:
    if value.lower() == "auto":
        if pos_count <= 0:
            raise SystemExit("--pos-weight auto requires at least one positive sample.")
        return neg_count / pos_count
    try:
        pos_weight = float(value)
    except ValueError as exc:
        raise SystemExit('--pos-weight must be a number or "auto".') from exc
    if pos_weight < 0:
        raise SystemExit("--pos-weight must be >= 0.")
    return pos_weight


# ---- 指标计算 ----

def compute_metrics(
    labels: list, logits: list
) -> tuple[float, float]:
    probs = torch.sigmoid(torch.tensor(logits)).numpy()
    preds = (probs >= 0.5).astype(int).flatten()
    labels_arr = np.array(labels).flatten()
    acc = accuracy_score(labels_arr, preds)
    try:
        auc = roc_auc_score(labels_arr, probs.flatten())
    except Exception:
        auc = 0.5
    return acc, auc


# ---- 训练 / 验证 ----

def scan_grouped_pairs(
    dataset_path: str,
    train_ratio: float,
    seed: int,
) -> tuple[list[tuple[str, list[tuple[str, str, str]]]], list[tuple[str, list[tuple[str, str, str]]]]]:
    """Return train/val folders with ordered (index, char_path, plan_path) pairs."""
    groups: list[tuple[str, list[tuple[str, str, str]]]] = []
    for root, _dirs, files in os.walk(dataset_path):
        char_files = [f for f in files if "char" in f.lower()]
        plan_files = [f for f in files if "plan" in f.lower()]
        if not char_files or not plan_files:
            continue

        char_dict: dict[str, str] = {}
        plan_dict: dict[str, str] = {}
        for filename in char_files:
            nums = re.findall(r"\d+", filename)
            if nums:
                char_dict[nums[0]] = os.path.join(root, filename)
        for filename in plan_files:
            nums = re.findall(r"\d+", filename)
            if nums:
                plan_dict[nums[0]] = os.path.join(root, filename)

        pairs: list[tuple[str, str, str]] = []
        for key in sorted(char_dict.keys(), key=lambda value: int(value)):
            if key in plan_dict:
                pairs.append((key, char_dict[key], plan_dict[key]))
        if pairs:
            groups.append((root, pairs))

    rng = random.Random(seed)
    rng.shuffle(groups)
    num_train = int(len(groups) * train_ratio)
    return groups[:num_train], groups[num_train:]


def build_pair_samples(
    groups: list[tuple[str, list[tuple[str, str, str]]]],
    negative_mode: str,
    seed: int,
) -> list[tuple[str, str, int]]:
    """Build author-style (char, plan, label) pairs."""
    rng = random.Random(seed)
    samples: list[tuple[str, str, int]] = []
    all_group_indices = list(range(len(groups)))

    for group_index, (_root, pairs) in enumerate(groups):
        for pair_index, (_key, char_path, plan_path) in enumerate(pairs):
            samples.append((char_path, plan_path, 1))

            if negative_mode in ("in-folder-all", "mixed-all"):
                for neg_index, (_neg_key, _neg_char, neg_plan) in enumerate(pairs):
                    if neg_index != pair_index:
                        samples.append((char_path, neg_plan, 0))

                if negative_mode == "mixed-all" and len(groups) > 1:
                    while True:
                        other_group_index = rng.choice(all_group_indices)
                        if other_group_index != group_index:
                            break
                    _other_root, other_pairs = groups[other_group_index]
                    _neg_key, _neg_char, neg_plan = rng.choice(other_pairs)
                    samples.append((char_path, neg_plan, 0))
                continue

            use_cross = (rng.random() < 0.5 or len(pairs) <= 1) and len(groups) > 1
            if use_cross:
                while True:
                    other_group_index = rng.choice(all_group_indices)
                    if other_group_index != group_index:
                        break
                _other_root, other_pairs = groups[other_group_index]
                _neg_key, _neg_char, neg_plan = rng.choice(other_pairs)
                samples.append((char_path, neg_plan, 0))
            elif len(pairs) > 1:
                while True:
                    neg_index = rng.randrange(len(pairs))
                    if neg_index != pair_index:
                        break
                _neg_key, _neg_char, neg_plan = pairs[neg_index]
                samples.append((char_path, neg_plan, 0))

    return samples


def load_pairs_csv(pairs_path: Path) -> tuple[list[tuple[str, str, int]], list[dict[str, object]]]:
    """Load yolo4 pairs.csv as (char_path, plan_path, label) samples plus row metadata."""
    root = pairs_path.resolve().parent
    samples: list[tuple[str, str, int]] = []
    rows: list[dict[str, object]] = []
    with pairs_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"sample", "plan_index", "char_index", "plan_file", "char_file", "label"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{pairs_path} missing columns: {sorted(missing)}")
        for row in reader:
            plan_path = root / str(row["plan_file"])
            char_path = root / str(row["char_file"])
            label = int(row["label"])
            samples.append((str(char_path), str(plan_path), label))
            rows.append(
                {
                    "sample": str(row["sample"]),
                    "plan_index": int(row["plan_index"]),
                    "char_index": int(row["char_index"]),
                    "char_target_index": int(row.get("char_target_index") or 0),
                    "label": label,
                    "char_path": str(char_path),
                    "plan_path": str(plan_path),
                }
            )
    return samples, rows


def optimal_assignment(sim: np.ndarray) -> list[tuple[int, int]]:
    from itertools import permutations

    n_rows, n_cols = sim.shape
    if n_rows == 0 or n_cols == 0 or n_rows > n_cols:
        return []
    best_score = -float("inf")
    best: list[tuple[int, int]] = []
    for perm in permutations(range(n_cols), n_rows):
        score = sum(float(sim[row, perm[row]]) for row in range(n_rows))
        if score > best_score:
            best_score = score
            best = [(row, perm[row]) for row in range(n_rows)]
    return best


def greedy_match(sim: np.ndarray) -> list[tuple[int, int]]:
    """Greedy matching — mirrors matchingMode.find_overall_index_fast for deployment."""
    mat = sim.astype(np.float64).copy()
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


def validate_rank_all3(
    model: nn.Module,
    groups: list[tuple[str, list[tuple[str, str, str]]]],
    device: torch.device,
    input_size: tuple[int, int],
    batch_size: int,
    workers: int,
) -> tuple[float, list[float]]:
    """Evaluate whether the 3x3 similarity matrix gives the correct ordered assignment."""
    eval_groups = [group for group in groups if len(group[1]) >= 3]
    if not eval_groups:
        return 0.0, [0.0, 0.0, 0.0]

    pair_samples: list[tuple[str, str, int]] = []
    meta: list[tuple[int, int, int]] = []
    for group_index, (_root, pairs) in enumerate(eval_groups):
        first_three = pairs[:3]
        for plan_index, (_plan_key, _plan_char, plan_path) in enumerate(first_three):
            for char_index, (_char_key, char_path, _char_plan) in enumerate(first_three):
                pair_samples.append((char_path, plan_path, int(char_index == plan_index)))
                meta.append((group_index, plan_index, char_index))

    dataset = SiameseDataset(pair_samples, input_shape=input_size, augment=False)
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=False,
        collate_fn=dataset_collate,
        num_workers=workers,
        pin_memory=str(device).startswith("cuda"),
    )

    matrices = [np.full((3, 3), -np.inf, dtype=np.float32) for _ in eval_groups]
    cursor = 0
    model.eval()
    with torch.no_grad():
        for images, _labels_tensor in tqdm(loader, desc="Rank val", leave=False):
            x1 = images[0].to(device)
            x2 = images[1].to(device)
            logits = model(x1, x2).detach().cpu().numpy().reshape(-1)
            probs = 1.0 / (1.0 + np.exp(-logits))
            for score in probs:
                group_index, plan_index, char_index = meta[cursor]
                matrices[group_index][plan_index, char_index] = float(score)
                cursor += 1

    all3 = 0
    per_pos = [0, 0, 0]
    for matrix in matrices:
        assignment = optimal_assignment(matrix)
        if len(assignment) == 3 and all(plan_index == char_index for plan_index, char_index in assignment):
            all3 += 1
        for plan_index in range(3):
            if int(np.argmax(matrix[plan_index])) == plan_index:
                per_pos[plan_index] += 1
    total = len(matrices)
    return all3 / total, [value / total for value in per_pos]


def validate_rank_pairs_csv(
    model: nn.Module,
    pair_rows: list[dict[str, object]],
    device: torch.device,
    input_size: tuple[int, int],
    batch_size: int,
    workers: int,
) -> tuple[float, list[float]]:
    """Evaluate 3-plan x 4-char ranking from yolo4 pairs.csv metadata."""
    if not pair_rows:
        return 0.0, [0.0, 0.0, 0.0]

    pair_samples = [
        (str(row["char_path"]), str(row["plan_path"]), int(row["label"]))
        for row in pair_rows
    ]
    dataset = SiameseDataset(pair_samples, input_shape=input_size, augment=False)
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=False,
        collate_fn=dataset_collate,
        num_workers=workers,
        pin_memory=str(device).startswith("cuda"),
    )

    scored_rows: list[tuple[dict[str, object], float]] = []
    cursor = 0
    model.eval()
    with torch.no_grad():
        for images, _labels_tensor in tqdm(loader, desc="Rank 3x4 val", leave=False):
            x1 = images[0].to(device)
            x2 = images[1].to(device)
            logits = model(x1, x2).detach().cpu().numpy().reshape(-1)
            probs = 1.0 / (1.0 + np.exp(-logits))
            for score in probs:
                scored_rows.append((pair_rows[cursor], float(score)))
                cursor += 1

    by_sample: dict[str, list[tuple[dict[str, object], float]]] = {}
    for row, score in scored_rows:
        by_sample.setdefault(str(row["sample"]), []).append((row, score))

    all3 = 0
    per_pos = [0, 0, 0]
    total = 0
    for sample_rows in by_sample.values():
        plan_indices = sorted({int(row["plan_index"]) for row, _score in sample_rows})
        char_indices = sorted({int(row["char_index"]) for row, _score in sample_rows})
        if len(plan_indices) != 3 or len(char_indices) < 3:
            continue
        plan_to_row = {value: idx for idx, value in enumerate(plan_indices)}
        char_to_col = {value: idx for idx, value in enumerate(char_indices)}
        matrix = np.full((len(plan_indices), len(char_indices)), -np.inf, dtype=np.float32)
        expected: dict[int, int] = {}
        for row, score in sample_rows:
            plan_index = int(row["plan_index"])
            char_index = int(row["char_index"])
            matrix[plan_to_row[plan_index], char_to_col[char_index]] = score
            if int(row["label"]) == 1:
                expected[plan_index] = char_index
        if len(expected) != 3:
            continue

        assignment = optimal_assignment(matrix)
        ok_all = len(assignment) == len(plan_indices)
        selected: dict[int, int] = {}
        for row_index, col_index in assignment:
            selected[plan_indices[row_index]] = char_indices[col_index]
        for plan_index in plan_indices:
            if selected.get(plan_index) == expected.get(plan_index):
                if 1 <= plan_index <= 3:
                    per_pos[plan_index - 1] += 1
            else:
                ok_all = False
        all3 += int(ok_all)
        total += 1

    if total == 0:
        return 0.0, [0.0, 0.0, 0.0]
    return all3 / total, [value / total for value in per_pos]


def resolve_device(value: str | None) -> torch.device:
    if value is None:
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    text = str(value).strip().lower()
    if text.isdigit():
        if torch.cuda.is_available():
            return torch.device(f"cuda:{text}")
        return torch.device("cpu")
    return torch.device(text)


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    optimizer: optim.Optimizer,
    device: torch.device,
    epoch: int,
    total_epochs: int,
    focal_gamma: float,
    label_smoothing: float,
    pos_weight: float,
) -> tuple[float, float, float]:
    model.train()
    total_loss: list[float] = []
    all_labels: list[float] = []
    all_logits: list[float] = []

    pbar = tqdm(loader, desc=f"Train {epoch}/{total_epochs}", leave=False)
    for images, labels_tensor in pbar:
        x1 = images[0].to(device)
        x2 = images[1].to(device)
        targets = labels_tensor.to(device).float().view(-1, 1)

        logits = model(x1, x2)
        loss = focal_bce_loss(
            logits,
            targets,
            gamma=focal_gamma,
            smoothing=label_smoothing,
            pos_weight=pos_weight,
        )

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        total_loss.append(loss.item())
        all_labels.extend(targets.cpu().tolist())
        all_logits.extend(logits.detach().cpu().tolist())
        pbar.set_postfix({"loss": f"{loss.item():.4f}"})

    avg_loss = np.mean(total_loss)
    acc, auc = compute_metrics(all_labels, all_logits)
    return avg_loss, acc, auc


def validate(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
    focal_gamma: float,
    label_smoothing: float,
    pos_weight: float,
) -> tuple[float, float, float]:
    model.eval()
    total_loss: list[float] = []
    all_labels: list[float] = []
    all_logits: list[float] = []

    pbar = tqdm(loader, desc="Validation", leave=False)
    with torch.no_grad():
        for images, labels_tensor in pbar:
            x1 = images[0].to(device)
            x2 = images[1].to(device)
            targets = labels_tensor.to(device).float().view(-1, 1)

            logits = model(x1, x2)
            loss = focal_bce_loss(
                logits,
                targets,
                gamma=focal_gamma,
                smoothing=label_smoothing,
                pos_weight=pos_weight,
            )

            total_loss.append(loss.item())
            all_labels.extend(targets.cpu().tolist())
            all_logits.extend(logits.cpu().tolist())
            pbar.set_postfix({"loss": f"{loss.item():.4f}"})

    avg_loss = np.mean(total_loss)
    acc, auc = compute_metrics(all_labels, all_logits)
    return avg_loss, acc, auc


# ---- ONNX 导出 (作者原版) ----

def export_onnx(model: nn.Module, path: Path, input_size: tuple[int, int] = (112, 112)) -> None:
    device = next(model.parameters()).device
    model = model.cpu().eval()

    x1 = torch.randn(1, 3, *input_size)
    x2 = torch.randn(1, 3, *input_size)

    torch.onnx.export(
        model,
        (x1, x2),
        str(path),
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=["input1", "input2"],
        output_names=["logits"],
        dynamic_axes={
            "input1": {0: "batch"},
            "input2": {0: "batch"},
            "logits": {0: "batch"},
        },
    )
    print(f"ONNX exported to: {path}")

    # 验证
    import onnxruntime
    session = onnxruntime.InferenceSession(str(path))
    test_x1 = np.random.randn(2, 3, *input_size).astype(np.float32)
    test_x2 = np.random.randn(2, 3, *input_size).astype(np.float32)
    outputs = session.run(None, {
        session.get_inputs()[0].name: test_x1,
        session.get_inputs()[1].name: test_x2,
    })
    print(f"ONNX validate OK. Output shape: {outputs[0].shape}")

    model.to(device)


# ---- 主训练流程 ----

def main() -> None:
    args = parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    # 设备
    device = resolve_device(args.device)
    print(f"Device: {device}")

    # 数据
    pair_csv_mode = args.train_pairs is not None or args.val_pairs is not None
    train_groups: list[tuple[str, list[tuple[str, str, str]]]] = []
    val_groups: list[tuple[str, list[tuple[str, str, str]]]] = []
    train_pair_rows: list[dict[str, object]] = []
    val_pair_rows: list[dict[str, object]] = []
    if pair_csv_mode:
        if args.train_pairs is None or args.val_pairs is None:
            raise SystemExit("--train-pairs and --val-pairs must be provided together.")
        if not args.train_pairs.exists():
            raise SystemExit(f"Train pairs CSV not found: {args.train_pairs}")
        if not args.val_pairs.exists():
            raise SystemExit(f"Val pairs CSV not found: {args.val_pairs}")
        train_samples, train_pair_rows = load_pairs_csv(args.train_pairs)
        val_samples, val_pair_rows = load_pairs_csv(args.val_pairs)
        print("Pair CSV mode:")
        print(f"  train_pairs={args.train_pairs.resolve()}")
        print(f"  val_pairs={args.val_pairs.resolve()}")
    else:
        data_path = str(args.data.resolve())
        if not Path(data_path).exists():
            raise SystemExit(f"Dataset not found: {data_path}\nRun convert_click3_to_siamese.py first.")
        train_groups, val_groups = scan_grouped_pairs(data_path, train_ratio=args.train_ratio, seed=args.seed)
        if not train_groups or not val_groups:
            raise SystemExit("Dataset split is empty; check --data and --train-ratio.")
        train_samples = build_pair_samples(train_groups, args.negative_mode, seed=args.seed)
        val_samples = build_pair_samples(val_groups, args.negative_mode, seed=args.seed + 1)
    pos_train = sum(1 for _, _, label in train_samples if label == 1)
    neg_train = sum(1 for _, _, label in train_samples if label == 0)
    pos_val = sum(1 for _, _, label in val_samples if label == 1)
    neg_val = sum(1 for _, _, label in val_samples if label == 0)
    if not pair_csv_mode:
        print(f"Grouped folders: train={len(train_groups)} val={len(val_groups)}")
    print(f"Pair samples: train={len(train_samples)} pos={pos_train} neg={neg_train}")
    print(f"Pair samples: val={len(val_samples)} pos={pos_val} neg={neg_val}")
    pos_weight = resolve_pos_weight(args.pos_weight, pos_train, neg_train)
    print(f"Loss pos_weight={pos_weight:.4f}")

    input_size = (112, 112)
    train_dataset = SiameseDataset(train_samples, input_shape=input_size, augment=True)
    val_dataset = SiameseDataset(val_samples, input_shape=input_size, augment=False)

    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch,
        shuffle=True,
        collate_fn=dataset_collate,
        num_workers=args.workers,
        pin_memory=str(device).startswith("cuda"),
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=args.batch,
        shuffle=False,
        collate_fn=dataset_collate,
        num_workers=args.workers,
    )

    # 模型
    print(f"Loading SiameseMobileNetV4 with pretrained backbone={not args.no_pretrained}...")
    model = SiameseMobileNetV4(pretrained=not args.no_pretrained).to(device)
    params = sum(p.numel() for p in model.parameters())
    print(f"Total parameters: {params:,}")

    # 分层学习率 (作者原版)
    optimizer = optim.AdamW(
        [
            {"params": model.backbone.parameters(), "lr": args.lr_backbone},
            {"params": model.fusion_head.parameters(), "lr": args.lr_head},
        ],
        weight_decay=args.weight_decay,
    )
    scheduler = CosineAnnealingLR(optimizer, T_max=args.epochs)

    # 保存目录
    save_dir = (args.project / args.name).resolve()
    if save_dir.exists() and not args.exist_ok:
        raise SystemExit(f"Output exists, use --exist-ok: {save_dir}")
    save_dir.mkdir(parents=True, exist_ok=True)

    best_path = save_dir / "best.pth"
    last_path = save_dir / "last.pth"

    best_score = -float("inf")
    early_stop_counter = 0
    history: list[dict] = []

    print(f"\nStart training for {args.epochs} epochs...")
    print(f"Save dir: {save_dir}")

    for epoch in range(1, args.epochs + 1):
        start_time = time.time()

        train_loss, train_acc, train_auc = train_one_epoch(
            model,
            train_loader,
            optimizer,
            device,
            epoch,
            args.epochs,
            args.focal_gamma,
            args.label_smoothing,
            pos_weight,
        )
        val_loss, val_acc, val_auc = validate(
            model,
            val_loader,
            device,
            args.focal_gamma,
            args.label_smoothing,
            pos_weight,
        )
        if pair_csv_mode:
            val_rank_all3, val_rank_per_pos = validate_rank_pairs_csv(
                model,
                val_pair_rows,
                device,
                input_size,
                args.batch,
                args.workers,
            )
        else:
            val_rank_all3, val_rank_per_pos = validate_rank_all3(
                model,
                val_groups,
                device,
                input_size,
                args.batch,
                args.workers,
            )
        scheduler.step()

        lr_bb = optimizer.param_groups[0]["lr"]
        lr_hd = optimizer.param_groups[1]["lr"]

        row = {
            "epoch": epoch,
            "train_loss": round(train_loss, 4),
            "train_acc": round(train_acc, 4),
            "train_auc": round(train_auc, 4),
            "val_loss": round(val_loss, 4),
            "val_acc": round(val_acc, 4),
            "val_auc": round(val_auc, 4),
            "val_rank_all3": round(val_rank_all3, 4),
            "val_rank_3x4_all3": round(val_rank_all3, 4) if pair_csv_mode else None,
            "val_rank_per_pos": [round(value, 4) for value in val_rank_per_pos],
            "pos_weight": round(pos_weight, 4),
        }
        history.append(row)
        current_score = {
            "val_acc": val_acc,
            "val_auc": val_auc,
            "val_rank_all3": val_rank_all3,
            "val_rank_3x4_all3": val_rank_all3,
        }[args.save_metric]

        elapsed = time.time() - start_time
        print(
            f"\nEpoch {epoch:03d}/{args.epochs} | {elapsed:.1f}s | "
            f"Train: loss={train_loss:.4f} acc={train_acc:.4f} auc={train_auc:.4f} | "
            f"Val: loss={val_loss:.4f} acc={val_acc:.4f} auc={val_auc:.4f} "
            f"rank_all3={val_rank_all3:.4f} pos={val_rank_per_pos} | "
            f"LR: bb={lr_bb:.2e} hd={lr_hd:.2e}"
        )

        # 保存 last
        torch.save(
            {
                "model": model.state_dict(),
                "args": vars(args),
                "epoch": epoch,
                "val_rank_all3": val_rank_all3,
                "val_rank_per_pos": val_rank_per_pos,
                "pos_weight": pos_weight,
            },
            last_path,
        )

        # 保存 best
        if current_score > best_score:
            best_score = current_score
            early_stop_counter = 0
            torch.save(
                {
                    "model": model.state_dict(),
                    "args": vars(args),
                    "epoch": epoch,
                    "val_acc": val_acc,
                    "val_auc": val_auc,
                    "val_rank_all3": val_rank_all3,
                    "val_rank_per_pos": val_rank_per_pos,
                    "pos_weight": pos_weight,
                },
                best_path,
            )
            print(f" => Best model saved ({args.save_metric}={current_score:.4f})")
        else:
            early_stop_counter += 1
            if early_stop_counter >= args.patience:
                print(f"Early stopping at epoch {epoch}. Best {args.save_metric}: {best_score:.4f}")
                break

    # 保存训练历史
    metrics = {
        "best_metric": args.save_metric,
        "best_score": best_score,
        "history": history,
    }
    (save_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nTraining finished. Best {args.save_metric}: {best_score:.4f}")
    print(f"Best model: {best_path}")

    # 导出 ONNX
    if args.export_onnx:
        checkpoint = torch.load(best_path, map_location="cpu", weights_only=False)
        model_export = SiameseMobileNetV4(pretrained=False)
        model_export.load_state_dict(checkpoint["model"])
        onnx_path = save_dir / "best.onnx"
        export_onnx(model_export, onnx_path, input_size=input_size)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
