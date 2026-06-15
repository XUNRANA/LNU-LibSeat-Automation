"""
v8 数据加载器 — 直接构造 (anchor, positive, negative) 三元组以匹配部署场景。

每个 sample_XXXXX 文件夹有 3 对 (char001/plan001, char002/plan002, char003/plan003)。
对每个 plan_i (anchor)，硬负例 = char_j (j != i) 同一文件夹 — 这正是部署里要区分的"同一 bg 不同字"。

每 epoch 三元组分布:
  - per-sample 硬负例: 每个 plan_i 配 (3 - 1) = 2 个 in-sample neg(char_j, j != i) → 6 triplets/sample
  - 跨样本 easy negative: 额外 30% 概率从其他文件夹随机取一个 char 做 negative，增加多样性

复用 v7 的图像预处理 (letterbox 128, RGB, /255, 112x112)。
"""

from __future__ import annotations

import os
import random
import re
from typing import Optional

import cv2
import numpy as np
import torch
from torch.utils.data.dataset import Dataset

from model.siamese_dataloader import cvtColor, letterbox_image, preprocess_input, rand


def discover_folders(dataset_path: str) -> list[dict]:
    """扫描数据集，返回 [{'folder': str, 'pairs': {idx: (char_path, plan_path)}}, ...]"""
    out: list[dict] = []
    for root, _, files in os.walk(dataset_path):
        char_files = [f for f in files if "char" in f.lower()]
        plan_files = [f for f in files if "plan" in f.lower()]
        if not char_files or not plan_files:
            continue
        char_dict: dict[str, str] = {}
        plan_dict: dict[str, str] = {}
        for f in char_files:
            nums = re.findall(r"\d+", f)
            if nums:
                char_dict[nums[0]] = os.path.join(root, f)
        for f in plan_files:
            nums = re.findall(r"\d+", f)
            if nums:
                plan_dict[nums[0]] = os.path.join(root, f)
        pairs = {idx: (char_dict[idx], plan_dict[idx]) for idx in char_dict if idx in plan_dict}
        if len(pairs) >= 2:  # 至少 2 对才能构造 in-sample hard neg
            out.append({"folder": root, "pairs": pairs})
    return out


def split_folders(
    folders: list[dict], train_ratio: float = 0.9, seed: int = 42
) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    shuffled = folders[:]
    rng.shuffle(shuffled)
    n_train = int(len(shuffled) * train_ratio)
    return shuffled[:n_train], shuffled[n_train:]


def build_triplets(
    folders: list[dict],
    cross_neg_prob: float = 0.3,
    seed: Optional[int] = None,
) -> list[tuple[str, str, str]]:
    """
    构造 (anchor_plan_path, pos_char_path, neg_char_path) 三元组列表。
    cross_neg_prob: 该比例的 triplet 用跨文件夹负例替代 in-sample 负例。
    """
    if seed is not None:
        rng = random.Random(seed)
    else:
        rng = random
    all_char_paths: list[str] = []
    for f in folders:
        for _, (cp, _) in f["pairs"].items():
            all_char_paths.append(cp)

    triplets: list[tuple[str, str, str]] = []
    for f in folders:
        idxs = list(f["pairs"].keys())
        if len(idxs) < 2:
            continue
        for anchor_idx in idxs:
            _, plan_path = f["pairs"][anchor_idx]
            pos_char, _ = f["pairs"][anchor_idx]
            # in-sample hard negatives: 每个 j != anchor_idx 都做一个
            for neg_idx in idxs:
                if neg_idx == anchor_idx:
                    continue
                neg_char, _ = f["pairs"][neg_idx]
                # 一定比例替换成跨文件夹负例
                if rng.random() < cross_neg_prob:
                    neg_char = rng.choice(all_char_paths)
                triplets.append((plan_path, pos_char, neg_char))
    return triplets


class TripletDataset(Dataset):
    """
    每个样本返回 (anchor_img, pos_img, neg_img)，全部已预处理为 (3, H, W) float32 RGB /255。
    augment 仅作用于训练集。
    """

    def __init__(
        self,
        triplets: list[tuple[str, str, str]],
        input_shape: tuple[int, int] = (112, 112),
        augment: bool = True,
    ) -> None:
        self.triplets = triplets
        self.input_shape = input_shape
        self.augment = augment

    def __len__(self) -> int:
        return len(self.triplets)

    def __getitem__(self, index: int):
        anchor_path, pos_path, neg_path = self.triplets[index]
        a = self._load(anchor_path)
        p = self._load(pos_path)
        n = self._load(neg_path)
        return a, p, n

    def _load(self, img_path: str) -> np.ndarray:
        img = cv2.imread(img_path)
        if img is None:
            raise FileNotFoundError(f"Cannot read: {img_path}")
        img = cvtColor(img)
        img = letterbox_image(img, self.input_shape)
        if self.augment:
            img = self._aug(img)
        img = preprocess_input(img)
        img = np.transpose(img, (2, 0, 1))
        return img

    def _aug(self, image: np.ndarray) -> np.ndarray:
        h, w = image.shape[:2]
        if rand() < 0.5:
            image = cv2.flip(image, 1)
        if rand() < 0.5:
            angle = np.random.randint(-15, 15)
            M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
            image = cv2.warpAffine(image, M, (w, h), borderValue=(128, 128, 128))
        if rand() < 0.5:
            hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV).astype(np.float32)
            hsv[:, :, 0] = (hsv[:, :, 0] + rand(-0.1, 0.1) * 180) % 180
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] * rand(0.3, 1.7), 0, 255)
            hsv[:, :, 2] = np.clip(hsv[:, :, 2] * rand(0.7, 1.3), 0, 255)
            image = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)
        return image


def triplet_collate(batch):
    a = torch.from_numpy(np.array([item[0] for item in batch])).float()
    p = torch.from_numpy(np.array([item[1] for item in batch])).float()
    n = torch.from_numpy(np.array([item[2] for item in batch])).float()
    return a, p, n


class RankingValDataset(Dataset):
    """
    验证用：每个样本返回该文件夹的 3 个 plan + 3 个 char + 1 个跨文件夹 distractor char。
    评估时对每个 sample 跑 3x4 cosine matrix + 贪心匹配，计算 all-3-correct。
    """

    def __init__(
        self,
        folders: list[dict],
        all_folders: list[dict],
        input_shape: tuple[int, int] = (112, 112),
        seed: int = 42,
    ) -> None:
        self.folders = [f for f in folders if len(f["pairs"]) >= 3]
        self.input_shape = input_shape
        # 为每个 val sample 预先确定一个跨样本 distractor，保证可复现
        rng = random.Random(seed)
        other_chars: list[str] = []
        for f in all_folders:
            for _, (cp, _) in f["pairs"].items():
                other_chars.append(cp)
        self.distractors: list[str] = []
        for f in self.folders:
            in_sample = {cp for _, (cp, _) in f["pairs"].items()}
            while True:
                cand = rng.choice(other_chars)
                if cand not in in_sample:
                    self.distractors.append(cand)
                    break

    def __len__(self) -> int:
        return len(self.folders)

    def __getitem__(self, index: int):
        f = self.folders[index]
        keys = sorted(f["pairs"].keys())[:3]  # 取前 3 个对，按编号
        plans = []
        chars = []
        for k in keys:
            cp, pp = f["pairs"][k]
            plans.append(self._load(pp))
            chars.append(self._load(cp))
        chars.append(self._load(self.distractors[index]))
        # plans: [3, 3, H, W]; chars: [4, 3, H, W]
        return (
            np.stack(plans, axis=0).astype(np.float32),
            np.stack(chars, axis=0).astype(np.float32),
        )

    def _load(self, img_path: str) -> np.ndarray:
        img = cv2.imread(img_path)
        if img is None:
            raise FileNotFoundError(f"Cannot read: {img_path}")
        img = cvtColor(img)
        img = letterbox_image(img, self.input_shape)
        img = preprocess_input(img)
        return np.transpose(img, (2, 0, 1))


def ranking_val_collate(batch):
    plans = torch.from_numpy(np.stack([b[0] for b in batch], axis=0)).float()  # (B, 3, 3, H, W)
    chars = torch.from_numpy(np.stack([b[1] for b in batch], axis=0)).float()  # (B, 4, 3, H, W)
    return plans, chars
