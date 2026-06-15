from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from ultralytics import YOLO


@dataclass(frozen=True)
class Box:
    conf: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0


def parse_float_list(values: list[str]) -> list[float]:
    out: list[float] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part:
                out.append(float(part))
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate plan+bg single-class char YOLO candidate coverage.")
    parser.add_argument("--dataset", type=Path, default=Path("dataset/click3_yolo_plan_bg_char_60_900_100"))
    parser.add_argument("--model", type=Path, default=Path("runs/click3/plan_bg_char60_yolov8s_900_100/weights/best.pt"))
    parser.add_argument("--split", default="val", choices=("train", "val", "test"))
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--iou", type=float, default=0.45)
    parser.add_argument("--max-det", type=int, default=300)
    parser.add_argument("--bg-y", type=float, default=44.0)
    parser.add_argument("--bg-h", type=float, default=160.0)
    parser.add_argument("--confs", nargs="+", default=["0.01", "0.03", "0.05", "0.10", "0.15", "0.20", "0.25"])
    parser.add_argument("--dists", nargs="+", default=["10", "14", "18", "22", "28", "35"])
    parser.add_argument("--output", type=Path, default=Path("runs/click3/plan_bg_char60_yolov8s_900_100/candidate_eval"))
    parser.add_argument("--vis-conf", type=float, default=0.05)
    parser.add_argument("--vis-count", type=int, default=24)
    parser.add_argument("--cols", type=int, default=4)
    parser.add_argument("--thumb-width", type=int, default=330)
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


def read_gt(label_path: Path, image_size: tuple[int, int]) -> list[tuple[float, float]]:
    image_w, image_h = image_size
    centers: list[tuple[float, float]] = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        _, x, y, _, _ = parts
        centers.append((float(x) * image_w, float(y) * image_h))
    return centers


def can_match_all(preds: list[Box], gts: list[tuple[float, float]], distance: float) -> bool:
    if len(preds) < len(gts):
        return False
    pred_centers = [pred.center for pred in preds]

    def backtrack(gt_index: int, used: set[int]) -> bool:
        if gt_index == len(gts):
            return True
        gx, gy = gts[gt_index]
        candidates: list[tuple[float, int]] = []
        for pred_index, (px, py) in enumerate(pred_centers):
            if pred_index in used:
                continue
            dist = math.hypot(px - gx, py - gy)
            if dist <= distance:
                candidates.append((dist, pred_index))
        for _, pred_index in sorted(candidates):
            used.add(pred_index)
            if backtrack(gt_index + 1, used):
                return True
            used.remove(pred_index)
        return False

    # Match hard targets first.
    ordered_gts = sorted(
        gts,
        key=lambda gt: sum(math.hypot(px - gt[0], py - gt[1]) <= distance for px, py in pred_centers),
    )
    old_gts = gts[:]
    gts[:] = ordered_gts
    try:
        return backtrack(0, set())
    finally:
        gts[:] = old_gts


def min_distances(preds: list[Box], gts: list[tuple[float, float]]) -> list[float]:
    if not preds:
        return [float("inf") for _ in gts]
    pred_centers = [pred.center for pred in preds]
    out: list[float] = []
    for gx, gy in gts:
        out.append(min(math.hypot(px - gx, py - gy) for px, py in pred_centers))
    return out


def draw_sample(image_path: Path, label_path: Path, preds: list[Box], bg_y: float, output_path: Path) -> None:
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = load_font(13)
    image_w, image_h = image.size
    gts = read_gt(label_path, image.size)

    draw.line([(0, bg_y), (image_w, bg_y)], fill=(255, 255, 255), width=1)
    for index, (gx, gy) in enumerate(gts, start=1):
        r = 5
        draw.ellipse([gx - r, gy - r, gx + r, gy + r], outline=(255, 255, 255), width=2)
        draw.text((gx + 6, gy - 8), f"G{index}", fill=(255, 255, 255), font=font)

    for index, pred in enumerate(sorted(preds, key=lambda p: p.conf, reverse=True), start=1):
        color = (0, 220, 132) if index <= 3 else (255, 176, 0)
        draw.rectangle([pred.x1, pred.y1, pred.x2, pred.y2], outline=color, width=2)
        cx, cy = pred.center
        draw.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=color)
        draw.text((pred.x1, max(0, pred.y1 - 15)), f"{index}:{pred.conf:.2f}", fill=color, font=font)

    text = image_path.stem
    draw.rectangle([0, 0, 120, 20], fill=(0, 0, 0))
    draw.text((4, 3), text, fill=(255, 255, 255), font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, quality=95)


def make_grid(paths: list[Path], output_path: Path, thumb_width: int, cols: int) -> None:
    images = [Image.open(path).convert("RGB") for path in paths]
    if not images:
        return
    thumbs: list[Image.Image] = []
    for image in images:
        scale = thumb_width / image.width
        thumb_h = int(round(image.height * scale))
        thumbs.append(image.resize((thumb_width, thumb_h), Image.Resampling.LANCZOS))
    rows = (len(thumbs) + cols - 1) // cols
    cell_h = max(thumb.height for thumb in thumbs)
    grid = Image.new("RGB", (thumb_width * cols, cell_h * rows), (28, 28, 28))
    for index, thumb in enumerate(thumbs):
        x = (index % cols) * thumb_width
        y = (index // cols) * cell_h
        grid.paste(thumb, (x, y))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    grid.save(output_path, quality=95)


def main() -> None:
    args = parse_args()
    confs = sorted(parse_float_list(args.confs))
    dists = sorted(parse_float_list(args.dists))
    min_conf = min(confs)
    dataset = args.dataset.resolve()
    image_dir = dataset / "images" / args.split
    label_dir = dataset / "labels" / args.split
    image_paths = sorted(image_dir.glob("*.png"))
    if not image_paths:
        raise FileNotFoundError(f"no images found in {image_dir}")

    args.output.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(args.model))

    records: list[dict[str, object]] = []
    predictions_by_sample: dict[str, list[Box]] = {}
    gt_by_sample: dict[str, list[tuple[float, float]]] = {}

    results = model.predict(
        source=[str(path) for path in image_paths],
        imgsz=args.imgsz,
        conf=min_conf,
        iou=args.iou,
        max_det=args.max_det,
        verbose=False,
        stream=True,
    )
    for image_path, result in zip(image_paths, results):
        label_path = label_dir / f"{image_path.stem}.txt"
        image = Image.open(image_path)
        image_w, image_h = image.size
        gts = read_gt(label_path, image.size)
        gt_by_sample[image_path.stem] = gts
        preds: list[Box] = []
        if result.boxes is not None and len(result.boxes) > 0:
            xyxy = result.boxes.xyxy.cpu().numpy()
            conf_arr = result.boxes.conf.cpu().numpy()
            for coords, score in zip(xyxy, conf_arr):
                x1, y1, x2, y2 = (float(value) for value in coords)
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                if 0 <= cx <= image_w and args.bg_y <= cy <= args.bg_y + args.bg_h:
                    preds.append(Box(float(score), x1, y1, x2, y2))
        preds.sort(key=lambda box: box.conf, reverse=True)
        predictions_by_sample[image_path.stem] = preds
        records.append({"sample": image_path.stem, "gt_count": len(gts), "preds": preds})

    summary_rows: list[dict[str, object]] = []
    for conf in confs:
        filtered_by_sample = {
            sample: [pred for pred in preds if pred.conf >= conf] for sample, preds in predictions_by_sample.items()
        }
        counts = [len(preds) for preds in filtered_by_sample.values()]
        count_ge3 = sum(count >= 3 for count in counts)
        all_min_dists = [
            dist
            for sample, preds in filtered_by_sample.items()
            for dist in min_distances(preds, gt_by_sample[sample])
            if math.isfinite(dist)
        ]
        mean_min_dist = sum(all_min_dists) / len(all_min_dists) if all_min_dists else float("inf")
        for dist in dists:
            all_ok = 0
            top3_ok = 0
            for sample, preds in filtered_by_sample.items():
                gts = list(gt_by_sample[sample])
                if can_match_all(list(preds), gts, dist):
                    all_ok += 1
                if can_match_all(list(preds[:3]), list(gt_by_sample[sample]), dist):
                    top3_ok += 1
            summary_rows.append(
                {
                    "conf": conf,
                    "dist": dist,
                    "samples": len(image_paths),
                    "avg_candidates": sum(counts) / len(counts),
                    "min_candidates": min(counts),
                    "max_candidates": max(counts),
                    "ge3_rate": count_ge3 / len(counts),
                    "mean_nearest_gt_dist": mean_min_dist,
                    "all_candidate_success": all_ok / len(image_paths),
                    "top3_success": top3_ok / len(image_paths),
                }
            )

    summary_path = args.output / f"summary_{args.split}.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    vis_paths: list[Path] = []
    for image_path in image_paths[: args.vis_count]:
        label_path = label_dir / f"{image_path.stem}.txt"
        preds = [pred for pred in predictions_by_sample[image_path.stem] if pred.conf >= args.vis_conf]
        output_path = args.output / "vis" / f"{image_path.stem}.jpg"
        draw_sample(image_path, label_path, preds, args.bg_y, output_path)
        vis_paths.append(output_path)
    grid_path = args.output / f"grid_{args.split}_conf{args.vis_conf:g}.jpg"
    make_grid(vis_paths, grid_path, args.thumb_width, args.cols)

    print(f"samples: {len(image_paths)}")
    print(f"summary: {summary_path}")
    print(f"grid: {grid_path}")
    print("conf dist avg_cand ge3 all_success top3_success mean_nearest")
    for row in summary_rows:
        if row["dist"] in (18.0, 22.0, 28.0):
            print(
                f"{row['conf']:.2f} {row['dist']:.0f} "
                f"{row['avg_candidates']:.2f} {row['ge3_rate']:.3f} "
                f"{row['all_candidate_success']:.3f} {row['top3_success']:.3f} "
                f"{row['mean_nearest_gt_dist']:.2f}"
            )


if __name__ == "__main__":
    main()
