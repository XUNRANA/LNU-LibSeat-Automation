"""统计 GT 100% 命中时，每图预测框数量分布。"""

from pathlib import Path
import math
import cv2
from ultralytics import YOLO
from collections import Counter


MODEL_PATH = Path("runs/click1/plan_bg_char60_yolov8s_900_100-2/weights/best.pt")
IMAGES_DIR = Path("dataset/click1_yolo_plan_bg_char_60_900_100/images")
LABELS_DIR = Path("dataset/click1_yolo_plan_bg_char_60_900_100/labels")
IOU = 0.45
IMGSZ = 640
MATCH_DIST = 25.0


def main():
    model = YOLO(str(MODEL_PATH))

    # conf=0.05 保证 100% recall
    count_dist = Counter()  # pred_count -> image_count
    fp_per_image = []  # 每图假阳性数

    for split in ("train", "val"):
        img_dir = IMAGES_DIR / split
        lbl_dir = LABELS_DIR / split
        images = sorted(img_dir.glob("*.png"))
        for img_path in images:
            image = cv2.imread(str(img_path))
            if image is None:
                continue
            h, w = image.shape[:2]

            # GT
            label_path = lbl_dir / f"{img_path.stem}.txt"
            gt_points = []
            if label_path.exists():
                for line in label_path.read_text().strip().splitlines():
                    parts = line.split()
                    if len(parts) == 5:
                        _, cx, cy, bw, bh = (float(x) for x in parts)
                        gt_points.append((cx * w, cy * h))

            # Predict
            result = model.predict(source=image, imgsz=IMGSZ, conf=0.05, iou=IOU, max_det=300, verbose=False)[0]
            pred_count = len(result.boxes) if result.boxes is not None else 0
            count_dist[pred_count] += 1

            # Count matched GT (should be 1 for click1)
            matched = 0
            if result.boxes is not None:
                for gx, gy in gt_points:
                    for box in result.boxes:
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                        bcx = (x1 + x2) / 2
                        bcy = (y1 + y2) / 2
                        if math.hypot(bcx - gx, bcy - gy) < MATCH_DIST:
                            matched += 1
                            break
            fp = pred_count - matched
            fp_per_image.append(max(0, fp))

    total = sum(count_dist.values())
    print("conf=0.05, GT 100% 命中时每图预测框数量分布:")
    print(f"{'框数':>6} {'图片数':>8} {'占比':>8}")
    for k in sorted(count_dist.keys()):
        print(f"{k:>6} {count_dist[k]:>8} {count_dist[k]/total*100:>7.1f}%")
    print()
    avg_fp = sum(fp_per_image) / len(fp_per_image)
    print(f"平均每图假阳性框数: {avg_fp:.2f}")
    print(f"平均每图总预测数: {sum(k*v for k,v in count_dist.items())/total:.2f}")


if __name__ == "__main__":
    main()
