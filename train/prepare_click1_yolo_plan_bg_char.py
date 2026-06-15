"""
YOLO 数据准备 — click1 (1个目标字符)。

基于 prepare_click3_yolo_plan_bg_char.py 改造：
  - target_count=1，每样本只有 1 个目标字符
  - target 裁剪坐标固定为 left=25, right=45, top=5, bottom=27
  - 合成图顶部放 1 个 plan 字符，底部放 bg 图
  - 单类 char（nc=1），60px 边界框
  - 按样本编号顺序：前 900 训练，后 100 测试

用法:
  python prepare_click1_yolo_plan_bg_char.py
  python prepare_click1_yolo_plan_bg_char.py --overwrite
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


CLASS_NAMES = ["char"]


@dataclass(frozen=True)
class LabeledSample:
    name: str
    folder: Path
    bg_path: Path
    target_path: Path
    points: list[dict[str, int]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare plan + bg single-class char YOLO dataset for click1.")
    parser.add_argument("--dataset", type=Path, default=Path("dataset/click1"))
    parser.add_argument("--output", type=Path, default=Path("dataset/click1_yolo_plan_bg_char_40_900_100"))
    parser.add_argument("--box-size", type=int, default=40)
    parser.add_argument("--train-count", type=int, default=900, help="Number of samples for training.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    # Fixed crop coordinates for click1 target character
    parser.add_argument("--plan-left", type=int, default=25)
    parser.add_argument("--plan-right", type=int, default=45)
    parser.add_argument("--plan-top", type=int, default=5)
    parser.add_argument("--plan-bottom", type=int, default=27)
    parser.add_argument("--plan-slot-height", type=int, default=44)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def find_labeled_samples(dataset: Path, max_samples: int = 1000) -> list[LabeledSample]:
    samples: list[LabeledSample] = []
    for folder in sorted(dataset.glob("sample_[0-9][0-9][0-9][0-9][0-9]")):
        if not folder.is_dir():
            continue
        if len(samples) >= max_samples:
            break
        label_path = folder / "label.json"
        if not label_path.exists():
            continue
        data = load_json(label_path)
        if int(data.get("target_count", 0)) != 1:
            continue
        points_raw = data.get("points", [])
        if not isinstance(points_raw, list) or len(points_raw) < 1:
            continue
        points: list[dict[str, int]] = []
        for point in points_raw[:1]:
            try:
                points.append({"x": int(round(float(point["x"]))), "y": int(round(float(point["y"])))})
            except Exception:
                points = []
                break
        if len(points) != 1:
            continue
        bg_path = folder / f"{folder.name}_bg.png"
        target_path = folder / f"{folder.name}_target.png"
        if not bg_path.exists() or not target_path.exists():
            continue
        samples.append(LabeledSample(str(data.get("sample") or folder.name), folder, bg_path, target_path, points))
    return samples


def split_samples(
    samples: list[LabeledSample],
    train_count: int,
) -> dict[str, list[LabeledSample]]:
    total = len(samples)
    if total <= train_count:
        raise SystemExit(f"Only {total} samples found, need at least {train_count + 1}")
    return {
        "train": samples[:train_count],
        "val": samples[train_count:],
        "test": [],
    }


def crop_with_padding(
    image: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    fill: tuple[int, int, int] = (255, 255, 255),
) -> np.ndarray:
    h, w = image.shape[:2]
    out_h = max(1, y2 - y1)
    out_w = max(1, x2 - x1)
    canvas = np.full((out_h, out_w, 3), fill, dtype=np.uint8)
    src_x1 = max(0, x1)
    src_y1 = max(0, y1)
    src_x2 = min(w, x2)
    src_y2 = min(h, y2)
    if src_x2 > src_x1 and src_y2 > src_y1:
        canvas[src_y1 - y1 : src_y2 - y1, src_x1 - x1 : src_x2 - x1] = image[src_y1:src_y2, src_x1:src_x2]
    return canvas


def extract_plan_crop(target_path: Path, left: int, right: int, top: int, bottom: int) -> Image.Image:
    image_bgr = cv2.imread(str(target_path), cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise RuntimeError(f"cannot read target image: {target_path}")
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    crop = crop_with_padding(image_rgb, left, top, right, bottom, fill=(255, 255, 255))
    return Image.fromarray(crop)


def clipped_yolo_box(cx: float, cy: float, image_w: int, image_h: int, box_size: int) -> tuple[float, float, float, float]:
    half = box_size / 2
    x1 = max(0.0, cx - half)
    y1 = max(0.0, cy - half)
    x2 = min(float(image_w), cx + half)
    y2 = min(float(image_h), cy + half)
    return (x1 + x2) / 2 / image_w, (y1 + y2) / 2 / image_h, (x2 - x1) / image_w, (y2 - y1) / image_h


def compose_plan_bg_image(
    sample: LabeledSample,
    left: int,
    right: int,
    top: int,
    bottom: int,
    plan_slot_height: int,
) -> tuple[Image.Image, dict[str, int]]:
    with Image.open(sample.bg_path) as bg_src:
        bg = bg_src.convert("RGB")

    plan_crop = extract_plan_crop(sample.target_path, left, right, top, bottom)
    canvas = Image.new("RGB", (bg.width, plan_slot_height + bg.height), (255, 255, 255))
    # Place single plan crop centered
    x = (bg.width - plan_crop.width) // 2
    y = (plan_slot_height - plan_crop.height) // 2
    canvas.paste(plan_crop, (x, y))
    canvas.paste(bg, (0, plan_slot_height))
    return canvas, {"bg_x": 0, "bg_y": plan_slot_height, "bg_w": bg.width, "bg_h": bg.height}


def write_data_yaml(output: Path) -> None:
    yaml_text = "\n".join(
        [
            f"path: {output.resolve().as_posix()}",
            "train: images/train",
            "val: images/val",
            "test: images/val",
            "nc: 1",
            "names:",
            "  0: char",
            "",
        ]
    )
    (output / "data.yaml").write_text(yaml_text, encoding="utf-8")
    (output / "classes.txt").write_text("\n".join(CLASS_NAMES) + "\n", encoding="utf-8")


def reset_output(output: Path, overwrite: bool) -> None:
    if output.exists():
        if not overwrite:
            raise SystemExit(f"output exists, use --overwrite to rebuild: {output}")
        shutil.rmtree(output)
    for split in ("train", "val", "test"):
        (output / "images" / split).mkdir(parents=True, exist_ok=True)
        (output / "labels" / split).mkdir(parents=True, exist_ok=True)


def main() -> None:
    args = parse_args()
    dataset = args.dataset.resolve()
    output = args.output.resolve()
    if not dataset.exists():
        raise SystemExit(f"dataset not found: {dataset}")
    if args.box_size <= 0:
        raise SystemExit("--box-size must be positive")

    samples = find_labeled_samples(dataset, max_samples=1000)
    if not samples:
        raise SystemExit(f"no complete 1-target samples found in: {dataset}")
    print(f"Found {len(samples)} labeled click1 samples")

    samples_by_split = split_samples(samples, args.train_count)
    reset_output(output, args.overwrite)

    manifest_rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for split_name, split_samples_list in samples_by_split.items():
        counts[split_name] = len(split_samples_list)
        for sample in split_samples_list:
            image, offsets = compose_plan_bg_image(
                sample, args.plan_left, args.plan_right, args.plan_top, args.plan_bottom, args.plan_slot_height
            )
            image_w, image_h = image.size
            image_name = f"{sample.name}.png"
            label_name = f"{sample.name}.txt"
            image.save(output / "images" / split_name / image_name)

            lines: list[str] = []
            for point in sample.points:
                cx = point["x"] + offsets["bg_x"]
                cy = point["y"] + offsets["bg_y"]
                box = clipped_yolo_box(cx, cy, image_w, image_h, args.box_size)
                lines.append(f"0 {box[0]:.6f} {box[1]:.6f} {box[2]:.6f} {box[3]:.6f}")
            (output / "labels" / split_name / label_name).write_text("\n".join(lines) + "\n", encoding="utf-8")

            manifest_rows.append(
                {
                    "sample": sample.name,
                    "split": split_name,
                    "image": f"images/{split_name}/{image_name}",
                    "label": f"labels/{split_name}/{label_name}",
                    "image_w": image_w,
                    "image_h": image_h,
                    "bg_x": offsets["bg_x"],
                    "bg_y": offsets["bg_y"],
                    "bg_w": offsets["bg_w"],
                    "bg_h": offsets["bg_h"],
                    "box_size": args.box_size,
                    "plan_left": args.plan_left,
                    "plan_right": args.plan_right,
                    "plan_top": args.plan_top,
                    "plan_bottom": args.plan_bottom,
                }
            )

    write_data_yaml(output)
    with (output / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(manifest_rows[0].keys()))
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"wrote {sum(counts.values())} images to {output}")
    print(f"split counts {counts}")
    print(f"data yaml {output / 'data.yaml'}")


if __name__ == "__main__":
    main()
