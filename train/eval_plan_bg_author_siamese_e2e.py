from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image, ImageDraw, ImageFont
from ultralytics import YOLO


THRESHOLDS = [8, 10, 14, 18, 22, 25, 28, 35]


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate plan+bg YOLO candidates + author Siamese ranking.")
    parser.add_argument("--raw-dataset", type=Path, default=Path("dataset/click3"))
    parser.add_argument("--yolo-dataset", type=Path, default=Path("dataset/click3_yolo_plan_bg_char_60_900_100"))
    parser.add_argument("--split", default="val", choices=("train", "val", "test"))
    parser.add_argument("--yolo", type=Path, default=Path("runs/click3/plan_bg_char60_yolov8s_900_100/weights/best.pt"))
    parser.add_argument(
        "--siamese",
        type=Path,
        default=Path("runs/click3_siamese_author/5_25_45_65_5_27_60/best.onnx"),
    )
    parser.add_argument("--output", type=Path, default=Path("runs/click3_siamese_author/5_25_45_65_5_27_60/e2e_eval.json"))
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--yolo-conf", type=float, default=0.05)
    parser.add_argument("--yolo-iou", type=float, default=0.45)
    parser.add_argument("--char-crop-size", type=int, default=60)
    parser.add_argument("--plan-x1", type=int, default=5)
    parser.add_argument("--plan-x2", type=int, default=25)
    parser.add_argument("--plan-x3", type=int, default=45)
    parser.add_argument("--plan-x4", type=int, default=65)
    parser.add_argument("--plan-y1", type=int, default=5)
    parser.add_argument("--plan-y2", type=int, default=27)
    parser.add_argument("--plan-slot-height", type=int, default=44)
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


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def preprocess_siamese(img_bgr: np.ndarray, input_size: tuple[int, int] = (112, 112)) -> np.ndarray:
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    h, w = input_size
    ih, iw = rgb.shape[:2]
    scale = min(w / iw, h / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    resized = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_CUBIC)
    canvas = np.full((h, w, 3), 128, dtype=np.uint8)
    dx, dy = (w - nw) // 2, (h - nh) // 2
    canvas[dy : dy + nh, dx : dx + nw] = resized
    arr = canvas.astype(np.float32) / 255.0
    return np.transpose(arr, (2, 0, 1))


def crop_with_padding(
    img: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    fill: tuple[int, int, int],
) -> np.ndarray:
    h, w = img.shape[:2]
    out = np.full((max(1, y2 - y1), max(1, x2 - x1), 3), fill, dtype=np.uint8)
    sx1, sy1 = max(0, x1), max(0, y1)
    sx2, sy2 = min(w, x2), min(h, y2)
    if sx2 > sx1 and sy2 > sy1:
        out[sy1 - y1 : sy2 - y1, sx1 - x1 : sx2 - x1] = img[sy1:sy2, sx1:sx2]
    return out


def extract_plan_crops(target_bgr: np.ndarray, args: argparse.Namespace) -> list[np.ndarray]:
    regions = [(args.plan_x1, args.plan_x2), (args.plan_x2, args.plan_x3), (args.plan_x3, args.plan_x4)]
    crops: list[np.ndarray] = []
    for x1, x2 in regions:
        crops.append(crop_with_padding(target_bgr, x1, args.plan_y1, x2, args.plan_y2, fill=(255, 255, 255)))
    return crops


def compose_plan_bg(target_bgr: np.ndarray, bg_bgr: np.ndarray, args: argparse.Namespace) -> np.ndarray:
    bg_h, bg_w = bg_bgr.shape[:2]
    canvas = np.full((args.plan_slot_height + bg_h, bg_w, 3), 255, dtype=np.uint8)
    plan_crops = extract_plan_crops(target_bgr, args)
    slot_w = bg_w // 3
    for index, crop in enumerate(plan_crops):
        ch, cw = crop.shape[:2]
        x = index * slot_w + (slot_w - cw) // 2
        y = (args.plan_slot_height - ch) // 2
        canvas[y : y + ch, x : x + cw] = crop
    canvas[args.plan_slot_height : args.plan_slot_height + bg_h, 0:bg_w] = bg_bgr
    return canvas


def load_sample(raw_dataset: Path, sample_name: str) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int]]] | None:
    folder = raw_dataset / sample_name
    label_path = folder / "label.json"
    if not label_path.exists():
        return None
    data = json.loads(label_path.read_text(encoding="utf-8"))
    target_path = folder / data.get("target", f"{sample_name}_target.png")
    bg_path = folder / data.get("bg", f"{sample_name}_bg.png")
    if not target_path.exists() or not bg_path.exists():
        return None
    target_bgr = cv2.imread(str(target_path), cv2.IMREAD_COLOR)
    bg_bgr = cv2.imread(str(bg_path), cv2.IMREAD_COLOR)
    if target_bgr is None or bg_bgr is None:
        return None
    points = [(int(round(float(p["x"]))), int(round(float(p["y"])))) for p in data["points"][:3]]
    return target_bgr, bg_bgr, points


def optimal_match(sim: np.ndarray) -> list[tuple[int, int]]:
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


def score_author_siamese(session: ort.InferenceSession, plan_crops: list[np.ndarray], char_crops: list[np.ndarray]) -> np.ndarray:
    input_names = [inp.name for inp in session.get_inputs()]
    output_name = session.get_outputs()[0].name
    x1_list: list[np.ndarray] = []
    x2_list: list[np.ndarray] = []
    for plan in plan_crops:
        for char in char_crops:
            # Training order is (char, plan). The fusion head is not fully symmetric.
            x1_list.append(preprocess_siamese(char))
            x2_list.append(preprocess_siamese(plan))
    x1 = np.stack(x1_list, axis=0).astype(np.float32)
    x2 = np.stack(x2_list, axis=0).astype(np.float32)
    logits = session.run([output_name], {input_names[0]: x1, input_names[1]: x2})[0]
    return sigmoid(logits.reshape(len(plan_crops), len(char_crops)))


def detect_yolo_candidates(model: YOLO, image_bgr: np.ndarray, args: argparse.Namespace) -> list[Box]:
    result = model.predict(
        source=image_bgr,
        imgsz=args.imgsz,
        conf=args.yolo_conf,
        iou=args.yolo_iou,
        max_det=300,
        verbose=False,
    )[0]
    boxes: list[Box] = []
    if result.boxes is None or len(result.boxes) == 0:
        return boxes
    xyxy = result.boxes.xyxy.cpu().numpy()
    confs = result.boxes.conf.cpu().numpy()
    image_h, image_w = image_bgr.shape[:2]
    for coords, conf in zip(xyxy, confs):
        x1, y1, x2, y2 = (float(value) for value in coords)
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        if 0 <= cx <= image_w and args.plan_slot_height <= cy <= image_h:
            boxes.append(Box(float(conf), x1, y1, x2, y2))
    boxes.sort(key=lambda box: box.conf, reverse=True)
    return boxes


def ordered_ok(pred: list[tuple[int, int]] | None, gt: list[tuple[int, int]], threshold: float) -> bool:
    if pred is None or len(pred) != len(gt):
        return False
    return all(math.hypot(px - gx, py - gy) <= threshold for (px, py), (gx, gy) in zip(pred, gt))


def solve_from_chars(
    session: ort.InferenceSession,
    plan_crops: list[np.ndarray],
    char_crops: list[np.ndarray],
    char_centers: list[tuple[int, int]],
) -> tuple[list[tuple[int, int]] | None, np.ndarray | None]:
    if len(char_crops) < 3:
        return None, None
    sim = score_author_siamese(session, plan_crops, char_crops)
    matches = optimal_match(sim)
    if len(matches) < 3:
        return None, sim
    return [char_centers[char_index] for _plan_index, char_index in matches], sim


def draw_vis(
    bg_bgr: np.ndarray,
    sample_name: str,
    gt: list[tuple[int, int]],
    pred: list[tuple[int, int]] | None,
    boxes: list[Box],
    plan_slot_height: int,
    output_path: Path,
) -> None:
    image = Image.fromarray(cv2.cvtColor(bg_bgr, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    font = load_font(14)
    for index, (x, y) in enumerate(gt, start=1):
        draw.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(255, 255, 255), width=2)
        draw.text((x + 6, y - 8), f"G{index}", fill=(255, 255, 255), font=font)
    if pred:
        for index, (x, y) in enumerate(pred, start=1):
            draw.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(0, 220, 132), width=2)
            draw.text((x + 7, y + 4), f"P{index}", fill=(0, 220, 132), font=font)
    for index, box in enumerate(boxes, start=1):
        x1, y1, x2, y2 = box.x1, box.y1 - plan_slot_height, box.x2, box.y2 - plan_slot_height
        draw.rectangle([x1, y1, x2, y2], outline=(255, 176, 0), width=1)
        draw.text((x1, max(0, y1 - 15)), f"{index}:{box.conf:.2f}", fill=(255, 176, 0), font=font)
    draw.rectangle([0, 0, 130, 22], fill=(0, 0, 0))
    draw.text((4, 3), sample_name, fill=(255, 255, 255), font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, quality=95)


def main() -> None:
    args = parse_args()
    image_dir = args.yolo_dataset / "images" / args.split
    sample_names = [path.stem for path in sorted(image_dir.glob("*.png"))]
    if args.max_samples > 0:
        sample_names = sample_names[: args.max_samples]
    if not sample_names:
        raise SystemExit(f"no split images found: {image_dir}")
    if not args.siamese.exists():
        raise SystemExit(f"siamese onnx not found: {args.siamese}")

    yolo = YOLO(str(args.yolo))
    siamese_session = ort.InferenceSession(str(args.siamese), providers=["CPUExecutionProvider"])

    summary: dict[str, object] = {
        "raw_dataset": str(args.raw_dataset.resolve()),
        "yolo_dataset": str(args.yolo_dataset.resolve()),
        "split": args.split,
        "yolo": str(args.yolo.resolve()),
        "siamese": str(args.siamese.resolve()),
        "samples": 0,
        "yolo_conf": args.yolo_conf,
        "char_crop_size": args.char_crop_size,
        "gt3_rank_success": 0,
        "avg_yolo_candidates": 0.0,
        "yolo_less_than_3": 0,
        **{f"gt3_ordered_success@{t}": 0 for t in THRESHOLDS},
        **{f"yolo_ordered_success@{t}": 0 for t in THRESHOLDS},
    }
    details: list[dict[str, object]] = []
    total_candidates = 0

    for sample_index, sample_name in enumerate(sample_names):
        loaded = load_sample(args.raw_dataset, sample_name)
        if loaded is None:
            continue
        target_bgr, bg_bgr, gt_points = loaded
        plan_crops = extract_plan_crops(target_bgr, args)

        half = args.char_crop_size // 2
        gt_char_crops = [
            crop_with_padding(bg_bgr, x - half, y - half, x + half, y + half, fill=(128, 128, 128))
            for x, y in gt_points
        ]
        gt_pred, gt_sim = solve_from_chars(siamese_session, plan_crops, gt_char_crops, gt_points)

        composed = compose_plan_bg(target_bgr, bg_bgr, args)
        boxes = detect_yolo_candidates(yolo, composed, args)
        total_candidates += len(boxes)
        yolo_centers = [(int(round(box.center[0])), int(round(box.center[1] - args.plan_slot_height))) for box in boxes]
        yolo_char_crops = [
            crop_with_padding(bg_bgr, x - half, y - half, x + half, y + half, fill=(128, 128, 128))
            for x, y in yolo_centers
        ]
        yolo_pred, yolo_sim = solve_from_chars(siamese_session, plan_crops, yolo_char_crops, yolo_centers)

        summary["samples"] = int(summary["samples"]) + 1
        summary["gt3_rank_success"] = int(summary["gt3_rank_success"]) + int(gt_pred == gt_points)
        summary["yolo_less_than_3"] = int(summary["yolo_less_than_3"]) + int(len(boxes) < 3)
        for threshold in THRESHOLDS:
            key_gt = f"gt3_ordered_success@{threshold}"
            key_yolo = f"yolo_ordered_success@{threshold}"
            summary[key_gt] = int(summary[key_gt]) + int(ordered_ok(gt_pred, gt_points, threshold))
            summary[key_yolo] = int(summary[key_yolo]) + int(ordered_ok(yolo_pred, gt_points, threshold))

        details.append(
            {
                "sample": sample_name,
                "gt": gt_points,
                "gt3_pred": gt_pred,
                "yolo_pred": yolo_pred,
                "yolo_candidates": yolo_centers,
                "yolo_confs": [round(box.conf, 4) for box in boxes],
                "gt3_success@25": ordered_ok(gt_pred, gt_points, 25),
                "yolo_success@25": ordered_ok(yolo_pred, gt_points, 25),
                "gt3_sim": None if gt_sim is None else np.round(gt_sim, 4).tolist(),
                "yolo_sim": None if yolo_sim is None else np.round(yolo_sim, 4).tolist(),
            }
        )

        if sample_index < args.vis_count:
            draw_vis(
                bg_bgr,
                sample_name,
                gt_points,
                yolo_pred,
                boxes,
                args.plan_slot_height,
                args.output.parent / "e2e_vis" / f"{sample_name}.jpg",
            )

    total = int(summary["samples"])
    if total:
        summary["avg_yolo_candidates"] = total_candidates / total
        summary["gt3_rank_success"] = int(summary["gt3_rank_success"]) / total
        summary["yolo_less_than_3"] = int(summary["yolo_less_than_3"]) / total
        for threshold in THRESHOLDS:
            key_gt = f"gt3_ordered_success@{threshold}"
            key_yolo = f"yolo_ordered_success@{threshold}"
            summary[key_gt] = int(summary[key_gt]) / total
            summary[key_yolo] = int(summary[key_yolo]) / total

    payload = {**summary, "details": details}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    printable = {key: value for key, value in summary.items()}
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    print(f"results: {args.output.resolve()}")


if __name__ == "__main__":
    main()
