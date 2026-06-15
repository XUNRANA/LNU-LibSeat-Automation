"""
Siamese 孪生网络数据加载器 — 完全按照作者 (道满PythonAI / yujia) 的原版实现。

数据集结构 (由 convert_click3_to_siamese.py 生成):
  dataset/click3_siamese/
    sample_00001/
      char001.png, plan001.png   ← 正样本对 (同一个字)
      char002.png, plan002.png
      char003.png, plan003.png
    sample_00002/
      ...

正样本构建: 同文件夹、同编号的 char/plan 对
负样本构建: 同文件夹、不同编号的 char/plan 对
"""

from __future__ import annotations

import os
import re
import random

import cv2
import numpy as np
import torch
from torch.utils.data.dataset import Dataset


# ---- 图像预处理 (作者原版) ----

def cvtColor(image_np: np.ndarray) -> np.ndarray:
    """确保图像为 3 通道 RGB 格式。"""
    if len(image_np.shape) == 3 and image_np.shape[2] == 3:
        return cv2.cvtColor(image_np, cv2.COLOR_BGR2RGB)
    elif len(image_np.shape) == 3 and image_np.shape[2] == 4:
        bgr = cv2.cvtColor(image_np, cv2.COLOR_BGRA2BGR)
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    else:
        return cv2.cvtColor(image_np, cv2.COLOR_GRAY2RGB)


def letterbox_image(image_np: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
    """保持宽高比缩放并居中填充 (灰色 128)。"""
    h, w = target_size
    ih, iw = image_np.shape[:2]
    scale = min(w / iw, h / ih)
    nw = int(iw * scale)
    nh = int(ih * scale)
    resized = cv2.resize(image_np, (nw, nh), interpolation=cv2.INTER_CUBIC)
    new_image = np.full((h, w, 3), 128, dtype=np.uint8)
    dx = (w - nw) // 2
    dy = (h - nh) // 2
    new_image[dy : dy + nh, dx : dx + nw] = resized
    return new_image


def preprocess_input(x: np.ndarray) -> np.ndarray:
    return x.astype(np.float32) / 255.0


def rand(a: float = 0.0, b: float = 1.0) -> float:
    return np.random.rand() * (b - a) + a


# ---- 数据集加载 (作者原版逻辑) ----

def load_dataset(
    dataset_path: str,
    train_ratio: float = 0.8,
) -> tuple[list[tuple[str, str, int]], list[tuple[str, str, int]]]:
    """
    扫描数据集目录，构建正负样本对并按文件夹整体划分训练/验证集。

    返回: (train_samples, val_samples)
    每个样本为 (char_path, plan_path, label)
    """
    folder_pairs: list[tuple[str, list[tuple[str, str]]]] = []

    for root, dirs, files in os.walk(dataset_path):
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

        pairs = []
        for num, char_path in char_dict.items():
            if num in plan_dict:
                pairs.append((char_path, plan_dict[num]))
        if pairs:
            folder_pairs.append((root, pairs))

    total_pairs = sum(len(p) for _, p in folder_pairs)
    print(f"共找到 {total_pairs} 个有效图像对，文件夹总数: {len(folder_pairs)}")

    # 按文件夹整体划分 (防数据泄漏)
    random.seed(42)
    random.shuffle(folder_pairs)
    num_train = int(len(folder_pairs) * train_ratio)
    train_folders = folder_pairs[:num_train]
    val_folders = folder_pairs[num_train:]

    def build_samples(folders: list[tuple[str, list[tuple[str, str]]]]) -> list[tuple[str, str, int]]:
        all_pairs: list[tuple[str, str, int]] = []  # (char, plan, folder_idx)
        for idx, (_, pairs) in enumerate(folders):
            for char_path, plan_path in pairs:
                all_pairs.append((char_path, plan_path, idx))

        folder_to_indices: dict[int, list[int]] = {}
        for i, (_, _, fidx) in enumerate(all_pairs):
            folder_to_indices.setdefault(fidx, []).append(i)

        all_folder_idxs = list(folder_to_indices.keys())

        samples: list[tuple[str, str, int]] = []
        for idx, (char_path, plan_path, fidx) in enumerate(all_pairs):
            # 正样本
            samples.append((char_path, plan_path, 1))

            # 负样本: 1 个，保持 1:1 平衡
            # 50% 概率选同文件夹负样本 (硬负例)，50% 概率选跨文件夹负样本 (多样性)
            other_indices = folder_to_indices[fidx]
            use_cross = (random.random() < 0.5) or len(other_indices) <= 1

            if use_cross and len(all_folder_idxs) > 1:
                # 跨文件夹负样本
                while True:
                    other_fidx = random.choice(all_folder_idxs)
                    if other_fidx != fidx:
                        break
                cross_idx = random.choice(folder_to_indices[other_fidx])
                _, neg_plan, _ = all_pairs[cross_idx]
                samples.append((char_path, neg_plan, 0))
            elif len(other_indices) > 1:
                # 同文件夹负样本
                while True:
                    neg_idx = random.choice(other_indices)
                    if neg_idx != idx:
                        break
                _, neg_plan, _ = all_pairs[neg_idx]
                samples.append((char_path, neg_plan, 0))

        return samples

    train_samples = build_samples(train_folders)
    val_samples = build_samples(val_folders)

    pos_train = sum(1 for _, _, label in train_samples if label == 1)
    neg_train = sum(1 for _, _, label in train_samples if label == 0)
    pos_val = sum(1 for _, _, label in val_samples if label == 1)
    neg_val = sum(1 for _, _, label in val_samples if label == 0)
    print(f"训练集样本数: {len(train_samples)} (正: {pos_train}, 负: {neg_train})")
    print(f"验证集样本数: {len(val_samples)} (正: {pos_val}, 负: {neg_val})")

    return train_samples, val_samples


# ---- PyTorch Dataset (作者原版) ----

class SiameseDataset(Dataset):
    def __init__(
        self,
        samples: list[tuple[str, str, int]],
        input_shape: tuple[int, int] = (112, 112),
        augment: bool = True,
    ) -> None:
        self.samples = samples
        self.input_shape = input_shape
        self.augment = augment

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int):
        img1_path, img2_path, label = self.samples[index]
        img1 = self._load_and_preprocess(img1_path)
        img2 = self._load_and_preprocess(img2_path)
        return [img1, img2], np.float32(label)

    def _load_and_preprocess(self, img_path: str) -> np.ndarray:
        image = cv2.imread(img_path)
        if image is None:
            raise FileNotFoundError(f"Cannot read image: {img_path}")
        image = cvtColor(image)
        image = letterbox_image(image, self.input_shape)

        if self.augment:
            image = self._apply_augment(image)

        image = preprocess_input(image)
        image = np.transpose(image, (2, 0, 1))  # HWC → CHW
        return image

    def _apply_augment(self, image: np.ndarray) -> np.ndarray:
        """作者原版数据增强：翻转 + 旋转 + HSV 色彩抖动。"""
        h, w = image.shape[:2]

        # 水平翻转
        if rand() < 0.5:
            image = cv2.flip(image, 1)

        # 随机旋转 ±15°
        if rand() < 0.5:
            angle = np.random.randint(-15, 15)
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            image = cv2.warpAffine(image, M, (w, h), borderValue=(128, 128, 128))

        # HSV 色彩抖动
        if rand() < 0.5:
            hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV).astype(np.float32)
            h_shift = rand(-0.1, 0.1) * 180
            s_scale = rand(1 - 0.7, 1 + 0.7)
            v_scale = rand(1 - 0.3, 1 + 0.3)
            hsv[:, :, 0] = (hsv[:, :, 0] + h_shift) % 180
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] * s_scale, 0, 255)
            hsv[:, :, 2] = np.clip(hsv[:, :, 2] * v_scale, 0, 255)
            image = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)

        return image


def dataset_collate(batch):
    """作者原版 collate_fn。"""
    left_imgs = [item[0][0] for item in batch]
    right_imgs = [item[0][1] for item in batch]
    labels = [item[1] for item in batch]

    left_tensor = torch.from_numpy(np.array(left_imgs)).float()
    right_tensor = torch.from_numpy(np.array(right_imgs)).float()
    labels_tensor = torch.from_numpy(np.array(labels)).float().view(-1, 1)

    images = torch.stack([left_tensor, right_tensor], dim=0)  # (2, B, C, H, W)
    return images, labels_tensor
