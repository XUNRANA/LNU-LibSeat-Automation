from __future__ import annotations

import argparse
import csv
import json
import random
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
    parser = argparse.ArgumentParser(description="Prepare plan1/plan2/plan3 + bg single-class char YOLO dataset.")
    parser.add_argument("--dataset", type=Path, default=Path("dataset/click3"))
    parser.add_argument("--output", type=Path, default=Path("dataset/click3_yolo_plan_bg_char_60_900_100"))
    parser.add_argument("--box-size", type=int, default=60)
    parser.add_argument("--train-ratio", type=float, default=0.9)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--no-test-split", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--plan-x1", type=int, default=5)
    parser.add_argument("--plan-x2", type=int, default=25)
    parser.add_argument("--plan-x3", type=int, default=45)
    parser.add_argument("--plan-x4", type=int, default=65)
    parser.add_argument("--plan-y1", type=int, default=5)
    parser.add_argument("--plan-y2", type=int, default=27)
    parser.add_argument("--plan-slot-height", type=int, default=44)
    parser.add_argument("--plan-padding", type=int, default=0)
    parser.add_argument("--manual-splits", type=Path, default=Path("dataset/manual_splits.json"))
    parser.add_argument("--use-manual-splits", action="store_true",
                        help="Use manual_splits.json. Default is fixed plan crop coordinates for every sample.")
    parser.add_argument("--ignore-manual-splits", action="store_true",
                        help="Deprecated compatibility flag; fixed crop coordinates are already the default.")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def find_labeled_samples(dataset: Path) -> list[LabeledSample]:
    samples: list[LabeledSample] = []
    for folder in sorted(dataset.glob("sample_[0-9][0-9][0-9][0-9][0-9]")):
        if not folder.is_dir():
            continue
        label_path = folder / "label.json"
        if not label_path.exists():
            continue
        data = load_json(label_path)
        if int(data.get("target_count", 0)) != 3:
            continue
        points_raw = data.get("points", [])
        if not isinstance(points_raw, list) or len(points_raw) < 3:
            continue
        points: list[dict[str, int]] = []
        for point in points_raw[:3]:
            try:
                points.append({"x": int(round(float(point["x"]))), "y": int(round(float(point["y"])))})
            except Exception:
                points = []
                break
        if len(points) != 3:
            continue
        bg_path = folder / f"{folder.name}_bg.png"
        target_path = folder / f"{folder.name}_target.png"
        if not bg_path.exists() or not target_path.exists():
            continue
        samples.append(LabeledSample(str(data.get("sample") or folder.name), folder, bg_path, target_path, points))
    return samples


def split_samples(
    samples: list[LabeledSample],
    train_ratio: float,
    val_ratio: float,
    seed: int,
    no_test_split: bool,
) -> dict[str, list[LabeledSample]]:
    shuffled = samples[:]
    random.Random(seed).shuffle(shuffled)
    total = len(shuffled)
    train_count = int(total * train_ratio)
    val_count = total - train_count if no_test_split else int(total * val_ratio)
    if total >= 3:
        if no_test_split:
            train_count = max(1, min(train_count, total - 1))
            val_count = max(1, total - train_count)
        else:
            train_count = max(1, min(train_count, total - 2))
            val_count = max(1, min(val_count, total - train_count - 1))
    return {
        "train": shuffled[:train_count],
        "val": shuffled[train_count : train_count + val_count],
        "test": [] if no_test_split else shuffled[train_count + val_count :],
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


def extract_plan_crops(target_path: Path, split: dict[str, int], padding: int) -> list[Image.Image]:
    image_bgr = cv2.imread(str(target_path), cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise RuntimeError(f"cannot read target image: {target_path}")
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    regions = [(split["x1"], split["x2"]), (split["x2"], split["x3"]), (split["x3"], split["x4"])]
    crops: list[Image.Image] = []
    for x1, x2 in regions:
        crop = crop_with_padding(
            image_rgb,
            x1 - padding,
            split["y1"] - padding,
            x2 + padding,
            split["y2"] + padding,
            fill=(255, 255, 255),
        )
        crops.append(Image.fromarray(crop))
    return crops


def clipped_yolo_box(cx: float, cy: float, image_w: int, image_h: int, box_size: int) -> tuple[float, float, float, float]:
    half = box_size / 2
    x1 = max(0.0, cx - half)
    y1 = max(0.0, cy - half)
    x2 = min(float(image_w), cx + half)
    y2 = min(float(image_h), cy + half)
    return (x1 + x2) / 2 / image_w, (y1 + y2) / 2 / image_h, (x2 - x1) / image_w, (y2 - y1) / image_h


def compose_plan_bg_image(
    sample: LabeledSample,
    split: dict[str, int],
    plan_slot_height: int,
    plan_padding: int,
) -> tuple[Image.Image, dict[str, int]]:
    with Image.open(sample.bg_path) as bg_src:
        bg = bg_src.convert("RGB")

    plan_crops = extract_plan_crops(sample.target_path, split, plan_padding)
    canvas = Image.new("RGB", (bg.width, plan_slot_height + bg.height), (255, 255, 255))
    slot_w = bg.width // 3
    for index, plan in enumerate(plan_crops):
        x = index * slot_w + (slot_w - plan.width) // 2
        y = (plan_slot_height - plan.height) // 2
        canvas.paste(plan, (x, y))
    canvas.paste(bg, (0, plan_slot_height))
    return canvas, {"bg_x": 0, "bg_y": plan_slot_height, "bg_w": bg.width, "bg_h": bg.height}


def write_data_yaml(output: Path, test_points_to_val: bool) -> None:
    yaml_text = "\n".join(
        [
            f"path: {output.resolve().as_posix()}",
            "train: images/train",
            "val: images/val",
            "test: images/val" if test_points_to_val else "test: images/test",
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
    if args.train_ratio <= 0 or args.val_ratio < 0:
        raise SystemExit("--train-ratio must be positive and --val-ratio must be non-negative")
    if args.no_test_split and args.train_ratio >= 1:
        raise SystemExit("--train-ratio must leave samples for val when --no-test-split is used")
    if not args.no_test_split and args.train_ratio + args.val_ratio >= 1:
        raise SystemExit("--train-ratio and --val-ratio must leave samples for test")

    default_split = {
        "x1": args.plan_x1,
        "x2": args.plan_x2,
        "x3": args.plan_x3,
        "x4": args.plan_x4,
        "y1": args.plan_y1,
        "y2": args.plan_y2,
    }
    manual_splits: dict[str, dict[str, int]] = {}
    if args.use_manual_splits and not args.ignore_manual_splits and args.manual_splits.exists():
        manual_splits = json.loads(args.manual_splits.read_text(encoding="utf-8"))
    else:
        print("Using fixed default plan crop coordinates for every sample.")

    samples = find_labeled_samples(dataset)
    if not samples:
        raise SystemExit(f"no complete 3-target samples found in: {dataset}")
    samples_by_split = split_samples(samples, args.train_ratio, args.val_ratio, args.seed, args.no_test_split)
    reset_output(output, args.overwrite)

    manifest_rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for split_name, split_samples_list in samples_by_split.items():
        counts[split_name] = len(split_samples_list)
        for sample in split_samples_list:
            split = manual_splits.get(sample.name, default_split)
            image, offsets = compose_plan_bg_image(sample, split, args.plan_slot_height, args.plan_padding)
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
                    "plan_x1": split["x1"],
                    "plan_x2": split["x2"],
                    "plan_x3": split["x3"],
                    "plan_x4": split["x4"],
                    "plan_y1": split["y1"],
                    "plan_y2": split["y2"],
                }
            )

    write_data_yaml(output, test_points_to_val=args.no_test_split)
    with (output / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(manifest_rows[0].keys()))
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"wrote {sum(counts.values())} images to {output}")
    print(f"split counts {counts}")
    print(f"data yaml {output / 'data.yaml'}")


if __name__ == "__main__":
    main()
