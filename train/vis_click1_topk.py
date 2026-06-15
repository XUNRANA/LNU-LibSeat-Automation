"""验证：取 top-K 预测框，GT 是否总在其中。"""

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


def main():
    model = YOLO(str(MODEL_PATH))

    data = []
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

            result = model.predict(source=image, imgsz=IMGSZ, conf=0.05, iou=IOU, max_det=300, verbose=False)[0]
            preds = []
            if result.boxes is not None:
                for box in result.boxes:
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    bcx = (x1 + x2) / 2
                    bcy = (y1 + y2) / 2
                    preds.append((conf, bcx, bcy))
            preds.sort(key=lambda x: x[0], reverse=True)
            data.append((gt_points, preds))

    print(f"{'top-K':>6} {'GT命中':>8} {'命中率':>8}")
    for k in range(1, 8):
        hit = 0
        total = 0
        for gt_points, preds in data:
            topk = preds[:k]
            for gx, gy in gt_points:
                total += 1
                for conf, bcx, bcy in topk:
                    if math.hypot(bcx - gx, bcy - gy) < MATCH_DIST:
                        hit += 1
                        break
        print(f"{k:>6} {hit:>5}/{total:<4} {hit/total*100:>7.1f}%")


if __name__ == "__main__":
    main()
