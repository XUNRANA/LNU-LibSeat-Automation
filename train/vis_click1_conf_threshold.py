"""不同置信度阈值下的 click1 YOLO 预测统计。"""

from pathlib import Path
import math
import cv2
from ultralytics import YOLO


MODEL_PATH = Path("runs/click1/plan_bg_char60_yolov8s_900_100-2/weights/best.pt")
IMAGES_DIR = Path("dataset/click1_yolo_plan_bg_char_60_900_100/images")
LABELS_DIR = Path("dataset/click1_yolo_plan_bg_char_60_900_100/labels")
IOU = 0.45
IMGSZ = 640
MATCH_DIST = 25.0
THRESHOLDS = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5]


def main():
    model = YOLO(str(MODEL_PATH))

    # Collect all predictions and GT
    all_data = []
    for split in ("train", "val"):
        img_dir = IMAGES_DIR / split
        lbl_dir = LABELS_DIR / split
        images = sorted(img_dir.glob("*.png"))
        for img_path in images:
            image = cv2.imread(str(img_path))
            if image is None:
                continue
            h, w = image.shape[:2]
            label_path = lbl_dir / f"{img_path.stem}.txt"
            gt_points = []
            if label_path.exists():
                for line in label_path.read_text().strip().splitlines():
                    parts = line.split()
                    if len(parts) == 5:
                        _, cx, cy, bw, bh = (float(x) for x in parts)
                        gt_points.append((cx * w, cy * h))
            result = model.predict(source=image, imgsz=IMGSZ, conf=0.01, iou=IOU, max_det=300, verbose=False)[0]
            preds = []
            if result.boxes is not None:
                for box in result.boxes:
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    preds.append((conf, float(x1), float(y1), float(x2), float(y2)))
            all_data.append((gt_points, preds))

    print(f"{'threshold':>10} {'avg_preds':>10} {'matched':>10} {'precision':>10} {'recall':>10}")
    for thresh in THRESHOLDS:
        total_preds = 0
        matched = 0
        total_gt = 0
        for gt_points, preds in all_data:
            filtered = [p for p in preds if p[0] >= thresh]
            total_preds += len(filtered)
            total_gt += len(gt_points)
            for gx, gy in gt_points:
                for conf, x1, y1, x2, y2 in filtered:
                    bcx = (x1 + x2) / 2
                    bcy = (y1 + y2) / 2
                    if math.hypot(bcx - gx, bcy - gy) < MATCH_DIST:
                        matched += 1
                        break
        n = len(all_data)
        avg = total_preds / n
        recall = matched / total_gt if total_gt > 0 else 0
        precision = matched / total_preds if total_preds > 0 else 0
        print(f"{thresh:>10.2f} {avg:>10.2f} {matched:>6}/{total_gt:<4} {precision:>10.2%} {recall:>10.2%}")


if __name__ == "__main__":
    main()
