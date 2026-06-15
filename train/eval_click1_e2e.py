"""Click1 end-to-end evaluation: raw target+bg -> YOLO candidates -> Siamese ranking -> accuracy."""

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
TOP_K = 4


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
    parser = argparse.ArgumentParser(description="Click1 e2e eval: YOLO candidates + Siamese ranking.")
    parser.add_argument("--raw-dataset", type=Path, default=Path("dataset/click1"))
    parser.add_argument("--yolo", type=Path, default=Path("runs/click1/plan_bg_char40_yolov8n_900_100/weights/best.pt"))
    parser.add_argument("--siamese", type=Path, default=Path("runs/click1_siamese_author/yolo4n_v8n_hard_up/best.onnx"))
    parser.add_argument("--siamese-pth", type=Path, default=Path("runs/click1_siamese_author/yolo4n_v8n_hard_up/best.pth"))
    parser.add_argument("--output", type=Path, default=Path("runs/click1_siamese_author/yolo4n_v8n_hard_up/e2e_eval.json"))
    parser.add_argument("--split", default="val", choices=("train", "val", "all"))
    parser.add_argument("--train-count", type=int, default=900)
    parser.add_argument("--val-count", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--yolo-conf", type=float, default=0.05)
    parser.add_argument("--yolo-iou", type=float, default=0.7)
    parser.add_argument("--char-crop-size", type=int, default=60)
    parser.add_argument("--plan-left", type=int, default=25)
    parser.add_argument("--plan-right", type=int, default=45)
    parser.add_argument("--plan-top", type=int, default=5)
    parser.add_argument("--plan-bottom", type=int, default=27)
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


def extract_plan_crop(target_bgr: np.ndarray, args: argparse.Namespace) -> np.ndarray:
    return crop_with_padding(
        target_bgr,
        args.plan_left,
        args.plan_top,
        args.plan_right,
        args.plan_bottom,
        fill=(255, 255, 255),
    )


def compose_plan_bg(plan_crop: np.ndarray, bg_bgr: np.ndarray, args: argparse.Namespace) -> np.ndarray:
    bg_h, bg_w = bg_bgr.shape[:2]
    canvas = np.full((args.plan_slot_height + bg_h, bg_w, 3), 255, dtype=np.uint8)
    ch, cw = plan_crop.shape[:2]
    x = (bg_w - cw) // 2
    y = (args.plan_slot_height - ch) // 2
    canvas[y : y + ch, x : x + cw] = plan_crop
    canvas[args.plan_slot_height : args.plan_slot_height + bg_h, 0:bg_w] = bg_bgr
    return canvas


def load_sample(raw_dataset: Path, sample_name: str) -> tuple[np.ndarray, np.ndarray, tuple[int, int]] | None:
    folder = raw_dataset / sample_name
    label_path = folder / "label.json"
    if not label_path.exists():
        return None
    data = json.loads(label_path.read_text(encoding="utf-8"))
    if data.get("target_count", 1) != 1:
        return None
    target_path = folder / data.get("target", f"{sample_name}_target.png")
    bg_path = folder / data.get("bg", f"{sample_name}_bg.png")
    if not target_path.exists() or not bg_path.exists():
        return None
    target_bgr = cv2.imread(str(target_path), cv2.IMREAD_COLOR)
    bg_bgr = cv2.imread(str(bg_path), cv2.IMREAD_COLOR)
    if target_bgr is None or bg_bgr is None:
        return None
    if len(data.get("points", [])) < 1:
        return None
    p = data["points"][0]
    gt = (int(round(float(p["x"]))), int(round(float(p["y"]))))
    return target_bgr, bg_bgr, gt


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


def score_siamese_onnx(
    session: ort.InferenceSession,
    plan_crop: np.ndarray,
    char_crops: list[np.ndarray],
) -> np.ndarray:
    input_names = [inp.name for inp in session.get_inputs()]
    output_name = session.get_outputs()[0].name
    x1_list: list[np.ndarray] = []
    x2_list: list[np.ndarray] = []
    for char in char_crops:
        x1_list.append(preprocess_siamese(char))
        x2_list.append(preprocess_siamese(plan_crop))
    x1 = np.stack(x1_list, axis=0).astype(np.float32)
    x2 = np.stack(x2_list, axis=0).astype(np.float32)
    logits = session.run([output_name], {input_names[0]: x1, input_names[1]: x2})[0]
    return sigmoid(logits.reshape(-1))


def score_siamese_pytorch(
    model,
    plan_crop: np.ndarray,
    char_crops: list[np.ndarray],
    device: str,
) -> np.ndarray:
    import torch
    plan_tensor = torch.from_numpy(preprocess_siamese(plan_crop)).unsqueeze(0).to(device)
    char_tensors = torch.stack([torch.from_numpy(preprocess_siamese(c)) for c in char_crops]).to(device)
    plan_batch = plan_tensor.expand(len(char_crops), -1, -1, -1)
    with torch.no_grad():
        logits = model(char_tensors, plan_batch).squeeze(-1).cpu().numpy()
    return sigmoid(logits)


def draw_vis(
    bg_bgr: np.ndarray,
    sample_name: str,
    gt: tuple[int, int],
    pred: tuple[int, int] | None,
    boxes: list[Box],
    plan_slot_height: int,
    output_path: Path,
) -> None:
    image = Image.fromarray(cv2.cvtColor(bg_bgr, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    font = load_font(14)
    x, y = gt
    draw.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(255, 255, 255), width=2)
    draw.text((x + 6, y - 8), "GT", fill=(255, 255, 255), font=font)
    if pred:
        px, py = pred
        draw.ellipse([px - 7, py - 7, px + 7, py + 7], outline=(0, 220, 132), width=2)
        draw.text((px + 7, py + 4), "P", fill=(0, 220, 132), font=font)
    for index, box in enumerate(boxes, start=1):
        bx1, by1 = box.x1, box.y1 - plan_slot_height
        bx2, by2 = box.x2, box.y2 - plan_slot_height
        draw.rectangle([bx1, by1, bx2, by2], outline=(255, 176, 0), width=1)
        draw.text((bx1, max(0, by1 - 15)), f"{index}:{box.conf:.2f}", fill=(255, 176, 0), font=font)
    draw.rectangle([0, 0, 130, 22], fill=(0, 0, 0))
    draw.text((4, 3), sample_name, fill=(255, 255, 255), font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, quality=95)


def main() -> None:
    args = parse_args()

    # Enumerate samples
    all_samples = sorted(
        p.name for p in args.raw_dataset.iterdir()
        if p.is_dir() and (p / "label.json").exists()
    )
    if args.split == "val":
        sample_names = [s for s in all_samples if args.train_count < int(s.split("_")[1]) <= args.train_count + args.val_count]
    elif args.split == "train":
        sample_names = [s for s in all_samples if int(s.split("_")[1]) <= args.train_count]
    else:
        sample_names = all_samples
    if args.max_samples > 0:
        sample_names = sample_names[: args.max_samples]
    if not sample_names:
        raise SystemExit(f"no samples found for split={args.split}")

    # Load models
    yolo = YOLO(str(args.yolo))
    siamese_session: ort.InferenceSession | None = None
    siamese_model = None
    siamese_device = "cpu"
    if args.siamese.exists():
        siamese_session = ort.InferenceSession(str(args.siamese), providers=["CPUExecutionProvider"])
        print(f"[info] Siamese ONNX: {args.siamese}")
    elif args.siamese_pth.exists():
        import torch
        from model.siamese_model import SiameseMobileNetV4
        siamese_device = "cuda" if torch.cuda.is_available() else "cpu"
        ckpt = torch.load(args.siamese_pth, map_location=siamese_device, weights_only=False)
        siamese_model = SiameseMobileNetV4(pretrained=False).to(siamese_device)
        siamese_model.load_state_dict(ckpt["model"])
        siamese_model.eval()
        print(f"[info] Siamese PyTorch: {args.siamese_pth} (device={siamese_device})")
    else:
        raise SystemExit(f"Siamese not found: {args.siamese} or {args.siamese_pth}")

    print(f"[info] YOLO: {args.yolo}")
    print(f"[info] Samples: {len(sample_names)} (split={args.split})")

    summary: dict[str, object] = {
        "raw_dataset": str(args.raw_dataset.resolve()),
        "split": args.split,
        "yolo": str(args.yolo.resolve()),
        "siamese": str(args.siamese.resolve()) if args.siamese.exists() else str(args.siamese_pth.resolve()),
        "samples": 0,
        "yolo_conf": args.yolo_conf,
        "yolo_iou": args.yolo_iou,
        "char_crop_size": args.char_crop_size,
        "yolo_coverage_25": 0,
        "siamese_rank_correct": 0,
        "siamese_rank_total": 0,
        "yolo_less_than_4": 0,
        **{f"e2e_success@{t}": 0 for t in THRESHOLDS},
    }
    details: list[dict[str, object]] = []
    total_candidates = 0

    half = args.char_crop_size // 2

    for sample_index, sample_name in enumerate(sample_names):
        loaded = load_sample(args.raw_dataset, sample_name)
        if loaded is None:
            continue
        target_bgr, bg_bgr, gt = loaded

        # Stage 1: compose + YOLO
        plan_crop = extract_plan_crop(target_bgr, args)
        composed = compose_plan_bg(plan_crop, bg_bgr, args)
        boxes = detect_yolo_candidates(yolo, composed, args)
        total_candidates += len(boxes)

        # YOLO coverage: is GT within 25px of any candidate?
        yolo_centers = [
            (int(round(box.center[0])), int(round(box.center[1] - args.plan_slot_height)))
            for box in boxes
        ]
        gt_covered = any(math.hypot(cx - gt[0], cy - gt[1]) <= 25 for cx, cy in yolo_centers)

        # Stage 2: Siamese ranking
        yolo_char_crops = [
            crop_with_padding(bg_bgr, x - half, y - half, x + half, y + half, fill=(128, 128, 128))
            for x, y in yolo_centers
        ]
        pred: tuple[int, int] | None = None
        siamese_picked_correct = False

        if yolo_char_crops:
            if siamese_session is not None:
                scores = score_siamese_onnx(siamese_session, plan_crop, yolo_char_crops)
            else:
                scores = score_siamese_pytorch(siamese_model, plan_crop, yolo_char_crops, siamese_device)
            best_idx = int(np.argmax(scores))
            pred = yolo_centers[best_idx]
            # Check if Siamese picked the GT-matching candidate
            if gt_covered:
                pred_dist = math.hypot(pred[0] - gt[0], pred[1] - gt[1])
                siamese_picked_correct = pred_dist <= 25

        # Accumulate
        n_samples = int(summary["samples"]) + 1
        summary["samples"] = n_samples
        summary["yolo_coverage_25"] = int(summary["yolo_coverage_25"]) + int(gt_covered)
        summary["yolo_less_than_4"] = int(summary["yolo_less_than_4"]) + int(len(boxes) < TOP_K)
        if gt_covered:
            summary["siamese_rank_total"] = int(summary["siamese_rank_total"]) + 1
            summary["siamese_rank_correct"] = int(summary["siamese_rank_correct"]) + int(siamese_picked_correct)

        for threshold in THRESHOLDS:
            key = f"e2e_success@{threshold}"
            success = pred is not None and math.hypot(pred[0] - gt[0], pred[1] - gt[1]) <= threshold
            summary[key] = int(summary[key]) + int(success)

        details.append({
            "sample": sample_name,
            "gt": list(gt),
            "pred": list(pred) if pred else None,
            "yolo_candidates": [list(c) for c in yolo_centers],
            "yolo_confs": [round(box.conf, 4) for box in boxes],
            "gt_covered": gt_covered,
            "siamese_correct": siamese_picked_correct,
            "dist": round(math.hypot(pred[0] - gt[0], pred[1] - gt[1]), 2) if pred else None,
        })

        if sample_index < args.vis_count:
            draw_vis(
                bg_bgr,
                sample_name,
                gt,
                pred,
                boxes,
                args.plan_slot_height,
                args.output.parent / "e2e_vis" / f"{sample_name}.jpg",
            )

    # Normalize
    total = int(summary["samples"])
    if total:
        summary["avg_yolo_candidates"] = round(total_candidates / total, 2)
        summary["yolo_coverage_25"] = round(int(summary["yolo_coverage_25"]) / total, 4)
        summary["yolo_less_than_4"] = int(summary["yolo_less_than_4"])
        rank_total = int(summary["siamese_rank_total"])
        if rank_total:
            summary["siamese_rank_accuracy"] = round(int(summary["siamese_rank_correct"]) / rank_total, 4)
        else:
            summary["siamese_rank_accuracy"] = 0.0
        for threshold in THRESHOLDS:
            key = f"e2e_success@{threshold}"
            summary[key] = round(int(summary[key]) / total, 4)

    payload = {**summary, "details": details}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    printable = {k: v for k, v in summary.items()}
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    print(f"results: {args.output.resolve()}")


if __name__ == "__main__":
    main()
