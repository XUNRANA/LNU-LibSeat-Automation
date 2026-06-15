"""统计 click1 YOLO 模型预测情况。"""

from pathlib import Path
import math
import cv2
from ultralytics import YOLO


MODEL_PATH = Path("runs/click1/plan_bg_char60_yolov8s_900_100-2/weights/best.pt")
IMAGES_DIR = Path("dataset/click1_yolo_plan_bg_char_60_900_100/images")
LABELS_DIR = Path("dataset/click1_yolo_plan_bg_char_60_900_100/labels")
CONF = 0.05
IOU = 0.45
IMGSZ = 640
MATCH_DIST = 25.0


def main():
    model = YOLO(str(MODEL_PATH))

    total_images = 0
    total_preds = 0
    total_gt = 0
    matched_gt = 0
    images_with_0_pred = 0
    images_with_1_pred = 0
    images_with_2plus_pred = 0
    conf_sum = 0.0
    conf_count = 0

    for split in ("train", "val"):
        img_dir = IMAGES_DIR / split
        lbl_dir = LABELS_DIR / split
        images = sorted(img_dir.glob("*.png"))

        for img_path in images:
            total_images += 1
            image = cv2.imread(str(img_path))
            if image is None:
                continue
            h, w = image.shape[:2]

            # Load GT
            label_path = lbl_dir / f"{img_path.stem}.txt"
            gt_points = []
            if label_path.exists():
                for line in label_path.read_text().strip().splitlines():
                    parts = line.split()
                    if len(parts) == 5:
                        _, cx, cy, bw, bh = (float(x) for x in parts)
                        gt_points.append((cx * w, cy * h))
            total_gt += len(gt_points)

            # Predict
            result = model.predict(source=image, imgsz=IMGSZ, conf=CONF, iou=IOU, max_det=300, verbose=False)[0]
            pred_count = len(result.boxes) if result.boxes is not None else 0
            total_preds += pred_count

            if pred_count == 0:
                images_with_0_pred += 1
            elif pred_count == 1:
                images_with_1_pred += 1
            else:
                images_with_2plus_pred += 1

            # Match predictions to GT
            if result.boxes is not None and len(gt_points) > 0:
                for box in result.boxes:
                    conf = float(box.conf[0])
                    conf_sum += conf
                    conf_count += 1
                    bx1, by1, bx2, by2 = box.xyxy[0].cpu().numpy()
                    bcx = (bx1 + bx2) / 2
                    bcy = (by1 + by2) / 2
                    for gx, gy in gt_points:
                        dist = math.hypot(bcx - gx, bcy - gy)
                        if dist < MATCH_DIST:
                            matched_gt += 1
                            break

    print(f"=== Click1 YOLO Prediction Stats (conf={CONF}) ===")
    print(f"Total images: {total_images}")
    print(f"Total GT boxes: {total_gt}")
    print(f"Total predictions: {total_preds}")
    print(f"Avg predictions/image: {total_preds/total_images:.2f}")
    print(f"Images with 0 predictions: {images_with_0_pred}")
    print(f"Images with 1 prediction: {images_with_1_pred}")
    print(f"Images with 2+ predictions: {images_with_2plus_pred}")
    print(f"GT matched (dist<{MATCH_DIST}px): {matched_gt}/{total_gt} = {matched_gt/total_gt*100:.1f}%")
    print(f"Avg prediction conf: {conf_sum/conf_count:.4f}" if conf_count > 0 else "No predictions")


if __name__ == "__main__":
    main()
