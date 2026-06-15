from __future__ import annotations

import sys

from auto_label_unlabeled_click3 import main


DEFAULT_ARGS = [
    "auto_label_unlabeled_click3.py",
    "--start",
    "1001",
    "--output-dir",
    "runs/click3_auto_label/gpu_from_1001_posw3",
    "--yolo",
    "runs/click3/plan_bg_char60_yolov8s_900_100_uniform/weights/best.pt",
    "--siamese",
    "runs/click3_siamese_author/yolo4_60_uniform_posw3/best.pth",
    "--yolo-device",
    "0",
    "--siamese-device",
    "0",
    "--top-k",
    "4",
    "--char-crop-size",
    "60",
    "--overwrite",
]


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv = DEFAULT_ARGS
    else:
        sys.argv = [DEFAULT_ARGS[0], *DEFAULT_ARGS[1:], *sys.argv[1:]]
    main()
