"""
Siamese 数据准备 — click1 (1个目标字符)。

基于 prepare_click3_siamese_yolo4.py 改造：
  - target_count=1，每样本只有 1 个目标字符
  - target 裁剪坐标固定为 left=25, right=45, top=5, bottom=27
  - 1-plan × 4-char 配对（vs click3 的 3-plan × 4-char）
  - 每样本 4 对（1 正 + 3 负）

用法:
  python prepare_click1_siamese_yolo4.py
  python prepare_click1_siamese_yolo4.py --overwrite
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from ultralytics import YOLO


@dataclass(frozen=True)
class Candidate:
    conf: float
    x1: float
    y1: float
    x2: float
    y2: float
    center_x: float
    center_y: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a 1-plan x 4-YOLO-candidate Siamese dataset from click1 raw samples."
    )
    parser.add_argument("--raw-dataset", type=Path, default=Path("dataset/click1"))
    parser.add_argument(
        "--split-images",
        type=Path,
        default=Path("dataset/click1_yolo_plan_bg_char_60_900_100/images/val"),
        help="Images whose stems define the sample list.",
    )
    parser.add_argument("--split-name", default="val")
    parser.add_argument("--output", type=Path, default=Path("dataset/click1_siamese_yolo4_val"))
    parser.add_argument("--yolo", type=Path, default=Path("runs/click1/plan_bg_char60_yolov8s_900_100/weights/best.pt"))
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.05)
    parser.add_argument("--iou", type=float, default=0.45)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--match-distance", type=float, default=25.0)
    parser.add_argument("--char-crop-size", type=int, default=60)
    # Fixed crop for click1
    parser.add_argument("--plan-left", type=int, default=25)
    parser.add_argument("--plan-right", type=int, default=45)
    parser.add_argument("--plan-top", type=int, default=5)
    parser.add_argument("--plan-bottom", type=int, default=27)
    parser.add_argument("--plan-slot-height", type=int, default=30)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--keep-incomplete", action="store_true", help="Keep samples even if YOLO misses a GT target.")
    parser.add_argument("--vis-count", type=int, default=24)
    parser.add_argument("--max-samples", type=int, default=0)
    return parser.parse_args()


def load_font(size: int) -> ImageFont.ImageFont:
    for path in (
        "C:/Windows/Fonts/consolab.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/msyh.ttc",
    ):
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def crop_with_padding(
    image: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    fill: tuple[int, int, int],
) -> np.ndarray:
    h, w = image.shape[:2]
    out_h = max(1, y2 - y1)
    out_w = max(1, x2 - x1)
    canvas = np.full((out_h, out_w, 3), fill, dtype=np.uint8)
    sx1, sy1 = max(0, x1), max(0, y1)
    sx2, sy2 = min(w, x2), min(h, y2)
    if sx2 > sx1 and sy2 > sy1:
        canvas[sy1 - y1 : sy2 - y1, sx1 - x1 : sx2 - x1] = image[sy1:sy2, sx1:sx2]
    return canvas


def load_raw_sample(raw_dataset: Path, sample_name: str) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int]], dict[str, Any]]:
    sample_dir = raw_dataset / sample_name
    label_path = sample_dir / "label.json"
    if not label_path.exists():
        raise FileNotFoundError(f"label not found: {label_path}")
    label = load_json(label_path)
    if int(label.get("target_count", 0)) != 1 or len(label.get("points", [])) < 1:
        raise ValueError(f"not a 1-target sample: {sample_name}")

    target_path = sample_dir / label.get("target", f"{sample_name}_target.png")
    bg_path = sample_dir / label.get("bg", f"{sample_name}_bg.png")
    target_bgr = cv2.imread(str(target_path), cv2.IMREAD_COLOR)
    bg_bgr = cv2.imread(str(bg_path), cv2.IMREAD_COLOR)
    if target_bgr is None:
        raise RuntimeError(f"cannot read target image: {target_path}")
    if bg_bgr is None:
        raise RuntimeError(f"cannot read bg image: {bg_path}")

    points = [(int(round(float(p["x"]))), int(round(float(p["y"])))) for p in label["points"][:1]]
    return target_bgr, bg_bgr, points, {"label": label, "target_path": target_path, "bg_path": bg_path}


def extract_plan_crop(target_bgr: np.ndarray, left: int, right: int, top: int, bottom: int) -> np.ndarray:
    return crop_with_padding(target_bgr, left, top, right, bottom, fill=(255, 255, 255))


def compose_plan_bg(plan_crop: np.ndarray, bg_bgr: np.ndarray, plan_slot_height: int) -> np.ndarray:
    bg_h, bg_w = bg_bgr.shape[:2]
    canvas = np.full((plan_slot_height + bg_h, bg_w, 3), 255, dtype=np.uint8)
    ch, cw = plan_crop.shape[:2]
    x = (bg_w - cw) // 2
    y = (plan_slot_height - ch) // 2
    canvas[y : y + ch, x : x + cw] = plan_crop
    canvas[plan_slot_height : plan_slot_height + bg_h, 0:bg_w] = bg_bgr
    return canvas


def detect_candidates(model: YOLO, image_bgr: np.ndarray, args: argparse.Namespace) -> list[Candidate]:
    result = model.predict(
        source=image_bgr,
        imgsz=args.imgsz,
        conf=args.conf,
        iou=args.iou,
        max_det=300,
        verbose=False,
    )[0]
    candidates: list[Candidate] = []
    if result.boxes is None or len(result.boxes) == 0:
        return candidates

    image_h, image_w = image_bgr.shape[:2]
    xyxy = result.boxes.xyxy.cpu().numpy()
    confs = result.boxes.conf.cpu().numpy()
    for coords, score in zip(xyxy, confs):
        x1, y1, x2, y2 = (float(value) for value in coords)
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        if 0 <= cx <= image_w and args.plan_slot_height <= cy <= image_h:
            candidates.append(Candidate(float(score), x1, y1, x2, y2, cx, cy - args.plan_slot_height))

    candidates.sort(key=lambda item: item.conf, reverse=True)
    return candidates[: args.top_k]


def match_candidate_to_gt(
    candidates: list[Candidate],
    gt_point: tuple[int, int],
    max_distance: float,
) -> tuple[int, float]:
    """Return the index of the candidate closest to gt_point, or -1 if none within max_distance."""
    best_idx = -1
    best_dist = float("inf")
    for ci, cand in enumerate(candidates):
        dist = math.hypot(cand.center_x - gt_point[0], cand.center_y - gt_point[1])
        if dist < best_dist:
            best_dist = dist
            best_idx = ci
    if best_dist > max_distance:
        return -1, best_dist
    return best_idx, best_dist


def draw_preview(
    bg_bgr: np.ndarray,
    sample_name: str,
    gt_point: tuple[int, int],
    candidates: list[Candidate],
    matched_idx: int,
    plan_slot_height: int,
    output_path: Path,
) -> None:
    image = Image.fromarray(cv2.cvtColor(bg_bgr, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    font = load_font(13)
    x, y = gt_point
    draw.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(255, 255, 255), width=2)
    draw.text((x + 6, y - 8), "G1", fill=(255, 255, 255), font=font)
    for ci, cand in enumerate(candidates):
        color = (0, 220, 132) if ci == matched_idx else (255, 176, 0)
        draw.rectangle([cand.x1, cand.y1 - plan_slot_height, cand.x2, cand.y2 - plan_slot_height], outline=color, width=2)
        label = f"C{ci+1}->P1" if ci == matched_idx else f"C{ci+1}->D"
        draw.text(
            (cand.x1, max(0, cand.y1 - plan_slot_height - 15)),
            f"{label} {cand.conf:.2f}",
            fill=color,
            font=font,
        )
    draw.rectangle([0, 0, 135, 22], fill=(0, 0, 0))
    draw.text((4, 3), sample_name, fill=(255, 255, 255), font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, quality=95)


def reset_output(output: Path, overwrite: bool) -> None:
    if output.exists():
        if not overwrite:
            raise SystemExit(f"output exists, use --overwrite: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)


def write_dataset_info(output: Path, args: argparse.Namespace) -> None:
    info = {
        "format": "click1_siamese_yolo4",
        "description": "Each sample has plan001 and char001-004. meta.json labels char_target_index 1 for match, 0 for distractor.",
        "raw_dataset": str(args.raw_dataset.resolve()),
        "split_images": str(args.split_images.resolve()),
        "split_name": args.split_name,
        "yolo": str(args.yolo.resolve()),
        "imgsz": args.imgsz,
        "conf": args.conf,
        "iou": args.iou,
        "top_k": args.top_k,
        "match_distance": args.match_distance,
        "char_crop_size": args.char_crop_size,
        "plan_crop": {
            "left": args.plan_left,
            "right": args.plan_right,
            "top": args.plan_top,
            "bottom": args.plan_bottom,
        },
    }
    (output / "dataset_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    if args.top_k < 4:
        raise SystemExit("--top-k should be at least 4 for a 1x4 Siamese dataset")
    if not args.raw_dataset.exists():
        raise SystemExit(f"raw dataset not found: {args.raw_dataset}")
    if not args.split_images.exists():
        raise SystemExit(f"split images path not found: {args.split_images}")
    if not args.yolo.exists():
        raise SystemExit(f"YOLO model not found: {args.yolo}")

    output = args.output.resolve()
    reset_output(output, args.overwrite)
    write_dataset_info(output, args)

    sample_names = [path.stem for path in sorted(args.split_images.glob("*.png"))]
    if args.max_samples > 0:
        sample_names = sample_names[: args.max_samples]
    if not sample_names:
        raise SystemExit(f"no sample images found in: {args.split_images}")

    model = YOLO(str(args.yolo))
    manifest_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    converted = 0
    skipped = 0
    incomplete = 0

    for sample_pos, sample_name in enumerate(sample_names):
        try:
            target_bgr, bg_bgr, gt_points, source_meta = load_raw_sample(args.raw_dataset, sample_name)
            plan_crop = extract_plan_crop(target_bgr, args.plan_left, args.plan_right, args.plan_top, args.plan_bottom)
            composed = compose_plan_bg(plan_crop, bg_bgr, args.plan_slot_height)
            candidates = detect_candidates(model, composed, args)
            matched_idx, nearest_dist = match_candidate_to_gt(candidates, gt_points[0], args.match_distance)

            is_complete = len(candidates) >= args.top_k and matched_idx >= 0
            if not is_complete:
                incomplete += 1
                if not args.keep_incomplete:
                    skipped += 1
                    manifest_rows.append(
                        {
                            "sample": sample_name,
                            "split": args.split_name,
                            "status": "skipped_incomplete",
                            "candidate_count": len(candidates),
                            "matched": matched_idx >= 0,
                        }
                    )
                    continue

            out_dir = output / sample_name
            out_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out_dir / "plan001.png"), plan_crop)

            char_items: list[dict[str, Any]] = []
            half = args.char_crop_size // 2
            for index, cand in enumerate(candidates[: args.top_k], start=1):
                cx = int(round(cand.center_x))
                cy = int(round(cand.center_y))
                crop = crop_with_padding(bg_bgr, cx - half, cy - half, cx + half, cy + half, fill=(128, 128, 128))
                filename = f"char{index:03d}.png"
                cv2.imwrite(str(out_dir / filename), crop)
                target_index = 1 if (index - 1) == matched_idx else 0
                char_item = {
                    "file": filename,
                    "char_index": index,
                    "char_target_index": target_index,
                    "is_distractor": target_index == 0,
                    "center": {"x": cx, "y": cy},
                    "conf": cand.conf,
                    "box_in_composed": [cand.x1, cand.y1, cand.x2, cand.y2],
                    "box_in_bg": [cand.x1, cand.y1 - args.plan_slot_height, cand.x2, cand.y2 - args.plan_slot_height],
                    "nearest_gt_distance": nearest_dist if (index - 1) == matched_idx else None,
                }
                char_items.append(char_item)

            pair_items: list[dict[str, Any]] = []
            for char_item in char_items:
                label = int(char_item["char_target_index"] == 1)
                pair = {
                    "sample": sample_name,
                    "split": args.split_name,
                    "plan_index": 1,
                    "char_index": char_item["char_index"],
                    "plan_file": f"{sample_name}/plan001.png",
                    "char_file": f"{sample_name}/{char_item['file']}",
                    "char_target_index": char_item["char_target_index"],
                    "label": label,
                    "center_x": char_item["center"]["x"],
                    "center_y": char_item["center"]["y"],
                    "conf": char_item["conf"],
                }
                pair_items.append(pair)
                pair_rows.append(pair)

            meta = {
                "sample": sample_name,
                "split": args.split_name,
                "target_path": str(source_meta["target_path"]),
                "bg_path": str(source_meta["bg_path"]),
                "target": {
                    "plan_files": ["plan001.png"],
                    "plan_crop": {
                        "left": args.plan_left,
                        "right": args.plan_right,
                        "top": args.plan_top,
                        "bottom": args.plan_bottom,
                    },
                },
                "gt_points": [{"target_index": 1, "x": gt_points[0][0], "y": gt_points[0][1]}],
                "yolo": {
                    "model": str(args.yolo),
                    "imgsz": args.imgsz,
                    "conf": args.conf,
                    "iou": args.iou,
                    "top_k": args.top_k,
                },
                "complete": is_complete,
                "chars": char_items,
                "pairs": pair_items,
            }
            (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

            if converted < args.vis_count:
                draw_preview(
                    bg_bgr,
                    sample_name,
                    gt_points[0],
                    candidates[: args.top_k],
                    matched_idx,
                    args.plan_slot_height,
                    output / "preview" / f"{sample_name}.jpg",
                )

            converted += 1
            manifest_rows.append(
                {
                    "sample": sample_name,
                    "split": args.split_name,
                    "status": "ok" if is_complete else "kept_incomplete",
                    "candidate_count": len(candidates),
                    "matched": matched_idx >= 0,
                }
            )
        except Exception as exc:
            skipped += 1
            manifest_rows.append(
                {
                    "sample": sample_name,
                    "split": args.split_name,
                    "status": f"error:{exc}",
                    "candidate_count": 0,
                    "matched": False,
                }
            )

    with (output / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        fieldnames = ["sample", "split", "status", "candidate_count", "matched"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest_rows)

    with (output / "pairs.csv").open("w", newline="", encoding="utf-8") as fh:
        fieldnames = [
            "sample",
            "split",
            "plan_index",
            "char_index",
            "plan_file",
            "char_file",
            "char_target_index",
            "label",
            "center_x",
            "center_y",
            "conf",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(pair_rows)

    print(f"samples requested: {len(sample_names)}")
    print(f"converted: {converted}")
    print(f"skipped: {skipped}")
    print(f"incomplete before filtering: {incomplete}")
    print(f"pairs: {len(pair_rows)}")
    print(f"output: {output}")
    print(f"manifest: {output / 'manifest.csv'}")
    print(f"pairs csv: {output / 'pairs.csv'}")


if __name__ == "__main__":
    main()
