from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from core.captcha_yolo4_siamese import Yolo4SiameseResult, Yolo4SiameseSolver


THRESHOLDS = [8, 10, 14, 18, 22, 25, 28, 35]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run YOLO4 + author Siamese end-to-end on click3.")
    parser.add_argument("--target", type=Path, default=None, help="Single target image path.")
    parser.add_argument("--bg", type=Path, default=None, help="Single bg image path.")
    parser.add_argument("--raw-dataset", type=Path, default=Path("dataset/click3"))
    parser.add_argument("--split-images", type=Path, default=Path("dataset/click3_yolo_plan_bg_char_60_900_100/images/val"))
    parser.add_argument("--output", type=Path, default=Path("runs/click3_siamese_author/yolo4_e2e_eval.json"))
    parser.add_argument("--yolo", type=Path, default=None)
    parser.add_argument("--siamese", type=Path, default=None)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--yolo-conf", type=float, default=0.05)
    parser.add_argument("--yolo-iou", type=float, default=0.45)
    parser.add_argument("--yolo-device", default="cpu")
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--char-crop-size", type=int, default=60)
    parser.add_argument("--tolerance", type=float, default=25.0)
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--vis-count", type=int, default=24)
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


def load_sample(raw_dataset: Path, sample_name: str) -> tuple[bytes, bytes, list[tuple[int, int]]] | None:
    sample_dir = raw_dataset / sample_name
    label_path = sample_dir / "label.json"
    if not label_path.exists():
        return None
    label = json.loads(label_path.read_text(encoding="utf-8"))
    target_path = sample_dir / label.get("target", f"{sample_name}_target.png")
    bg_path = sample_dir / label.get("bg", f"{sample_name}_bg.png")
    if not target_path.exists() or not bg_path.exists():
        return None
    points = [(int(round(float(p["x"]))), int(round(float(p["y"])))) for p in label["points"][:3]]
    return target_path.read_bytes(), bg_path.read_bytes(), points


def ordered_ok(pred: list[tuple[int, int]] | None, gt: list[tuple[int, int]], threshold: float) -> bool:
    if pred is None or len(pred) != len(gt):
        return False
    return all(math.hypot(px - gx, py - gy) <= threshold for (px, py), (gx, gy) in zip(pred, gt))


def distances(pred: list[tuple[int, int]] | None, gt: list[tuple[int, int]]) -> list[float] | None:
    if pred is None or len(pred) != len(gt):
        return None
    return [round(math.hypot(px - gx, py - gy), 2) for (px, py), (gx, gy) in zip(pred, gt)]


def draw_vis(bg_bytes: bytes, sample_name: str, gt: list[tuple[int, int]], result: Yolo4SiameseResult, output_path: Path) -> None:
    image = Image.open(__import__("io").BytesIO(bg_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = load_font(13)
    for index, (x, y) in enumerate(gt, start=1):
        draw.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(255, 255, 255), width=2)
        draw.text((x + 6, y - 8), f"G{index}", fill=(255, 255, 255), font=font)
    for index, (x, y) in enumerate(result.candidates, start=1):
        color = (255, 176, 0)
        draw.rectangle([x - 30, y - 30, x + 30, y + 30], outline=color, width=1)
        draw.text((x - 30, max(0, y - 45)), f"C{index}:{result.candidate_confidences[index-1]:.2f}", fill=color, font=font)
    for index, (x, y) in enumerate(result.points, start=1):
        draw.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(0, 220, 132), width=2)
        draw.text((x + 7, y + 3), f"P{index}", fill=(0, 220, 132), font=font)
    draw.rectangle([0, 0, 135, 22], fill=(0, 0, 0))
    draw.text((4, 3), sample_name, fill=(255, 255, 255), font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, quality=95)


def make_solver(args: argparse.Namespace) -> Yolo4SiameseSolver:
    kwargs = {
        "yolo_imgsz": args.imgsz,
        "yolo_conf": args.yolo_conf,
        "yolo_iou": args.yolo_iou,
        "yolo_device": args.yolo_device,
        "top_k": args.top_k,
        "char_crop_size": args.char_crop_size,
    }
    if args.yolo is not None:
        kwargs["yolo_path"] = args.yolo
    if args.siamese is not None:
        kwargs["siamese_path"] = args.siamese
    return Yolo4SiameseSolver(**kwargs)


def run_single(args: argparse.Namespace) -> None:
    if args.target is None or args.bg is None:
        raise SystemExit("--target and --bg must be provided together for single-image inference")
    solver = make_solver(args)
    result = solver.solve(args.target.read_bytes(), args.bg.read_bytes(), return_details=True)
    if result is None:
        print(json.dumps({"ok": False, "points": None}, ensure_ascii=False, indent=2))
        return
    assert isinstance(result, Yolo4SiameseResult)
    print(
        json.dumps(
            {
                "ok": True,
                "points": result.points,
                "candidates": result.candidates,
                "candidate_confidences": [round(v, 4) for v in result.candidate_confidences],
                "similarity": np.round(np.array(result.similarity), 4).tolist(),
                "yolo": str(solver.yolo_path),
                "siamese": str(solver.siamese_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def run_dataset(args: argparse.Namespace) -> None:
    solver = make_solver(args)
    sample_names = [path.stem for path in sorted(args.split_images.glob("*.png"))]
    if args.max_samples > 0:
        sample_names = sample_names[: args.max_samples]
    if not sample_names:
        raise SystemExit(f"no split images found: {args.split_images}")

    success_counts = {f"ordered_success@{threshold}": 0 for threshold in THRESHOLDS}
    no_prediction = 0
    total_candidates = 0
    results: list[dict[str, object]] = []

    for index, sample_name in enumerate(sample_names):
        loaded = load_sample(args.raw_dataset, sample_name)
        if loaded is None:
            continue
        target_bytes, bg_bytes, gt = loaded
        result = solver.solve(target_bytes, bg_bytes, return_details=True)
        pred: list[tuple[int, int]] | None = None
        candidates: list[tuple[int, int]] = []
        confs: list[float] = []
        sim = None
        if isinstance(result, Yolo4SiameseResult):
            pred = result.points
            candidates = result.candidates
            confs = [round(v, 4) for v in result.candidate_confidences]
            sim = np.round(np.array(result.similarity), 4).tolist()
            total_candidates += len(result.candidates)
            if index < args.vis_count:
                draw_vis(bg_bytes, sample_name, gt, result, args.output.parent / "yolo4_e2e_vis" / f"{sample_name}.jpg")
        else:
            no_prediction += 1

        for threshold in THRESHOLDS:
            success_counts[f"ordered_success@{threshold}"] += int(ordered_ok(pred, gt, threshold))

        results.append(
            {
                "sample": sample_name,
                "gt": gt,
                "pred": pred,
                "distances": distances(pred, gt),
                "candidates": candidates,
                "candidate_confidences": confs,
                "similarity": sim,
                f"ordered_success@{args.tolerance:g}": ordered_ok(pred, gt, args.tolerance),
            }
        )

    total = len(results)
    summary = {
        "raw_dataset": str(args.raw_dataset.resolve()),
        "split_images": str(args.split_images.resolve()),
        "yolo": str(solver.yolo_path),
        "siamese": str(solver.siamese_path),
        "samples": total,
        "yolo_conf": args.yolo_conf,
        "top_k": args.top_k,
        "char_crop_size": args.char_crop_size,
        "avg_candidates": total_candidates / total if total else 0,
        "no_prediction_rate": no_prediction / total if total else 0,
        **{key: value / total if total else 0 for key, value in success_counts.items()},
    }
    payload = {**summary, "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"results: {args.output.resolve()}")


def main() -> None:
    args = parse_args()
    if args.target is not None or args.bg is not None:
        run_single(args)
    else:
        run_dataset(args)


if __name__ == "__main__":
    main()
