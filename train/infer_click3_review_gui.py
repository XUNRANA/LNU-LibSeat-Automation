from __future__ import annotations

import argparse
import json
import re
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox
from typing import Any

from PIL import Image, ImageTk

from core.captcha_yolo4_siamese import Yolo4SiameseResult, Yolo4SiameseSolver


SAMPLE_RE = re.compile(r"^sample_(\d{5})$")
POINT_COLORS = {
    1: "#00d084",
    2: "#ffb000",
    3: "#ff4d6d",
}


@dataclass
class Sample:
    name: str
    index: int
    folder: Path
    bg_path: Path
    target_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CPU inference review GUI for click3 YOLO4 + Siamese labels.")
    parser.add_argument("--dataset", type=Path, default=Path("dataset/click3"))
    parser.add_argument("--scale", type=float, default=2.0)
    parser.add_argument("--start", type=int, default=None)
    parser.add_argument("--include-labeled", action="store_true", help="Also show samples that already have label.json.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("runs/click3_auto_label/gui_cpu_review"),
        help="Stores per-sample prediction JSON for later review. Does not write dataset label.json.",
    )
    parser.add_argument(
        "--yolo",
        type=Path,
        default=Path("runs/click3/plan_bg_char60_yolov8s_900_100_uniform/weights/best.pt"),
    )
    parser.add_argument(
        "--siamese",
        type=Path,
        default=Path("runs/click3_siamese_author/yolo4_60_uniform_posw3/best.pth"),
    )
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--yolo-conf", type=float, default=0.05)
    parser.add_argument("--yolo-iou", type=float, default=0.45)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--char-crop-size", type=int, default=60)
    return parser.parse_args()


def find_samples(dataset: Path, include_labeled: bool) -> list[Sample]:
    samples: list[Sample] = []
    for folder in sorted(dataset.iterdir()):
        if not folder.is_dir():
            continue
        match = SAMPLE_RE.match(folder.name)
        if not match:
            continue
        if not include_labeled and (folder / "label.json").exists():
            continue
        bg_path = folder / f"{folder.name}_bg.png"
        target_path = folder / f"{folder.name}_target.png"
        if not bg_path.exists() or not target_path.exists():
            continue
        samples.append(
            Sample(
                name=folder.name,
                index=int(match.group(1)),
                folder=folder,
                bg_path=bg_path,
                target_path=target_path,
            )
        )
    return samples


def make_label_payload(sample: Sample, points: list[tuple[int, int]]) -> dict[str, Any]:
    return {
        "sample": sample.name,
        "target_count": 3,
        "points": [{"x": int(x), "y": int(y)} for x, y in points],
        "bg": sample.bg_path.name,
        "target": sample.target_path.name,
    }


def min_match_margin(result: Yolo4SiameseResult) -> float:
    margins: list[float] = []
    for plan_index, char_index in result.matches:
        row = result.similarity[plan_index]
        selected = float(row[char_index])
        others = [float(value) for index, value in enumerate(row) if index != char_index]
        margins.append(selected - max(others) if others else 0.0)
    return min(margins) if margins else 0.0


class InferenceReviewApp:
    def __init__(self, root: tk.Tk, args: argparse.Namespace, samples: list[Sample]) -> None:
        self.root = root
        self.args = args
        self.samples = samples
        self.current_index = 0
        self.bg_image: Image.Image | None = None
        self.bg_photo: ImageTk.PhotoImage | None = None
        self.target_photo: ImageTk.PhotoImage | None = None
        self.result: Yolo4SiameseResult | None = None
        self.elapsed_ms: float | None = None
        self.attempt_count = 0
        self.status_text = "点击“推理”开始 CPU 推理"

        if args.start is not None:
            for index, sample in enumerate(samples):
                if sample.index >= args.start:
                    self.current_index = index
                    break

        self.output_dir = args.output_dir.resolve()
        self.pred_dir = self.output_dir / "predictions"
        self.pred_dir.mkdir(parents=True, exist_ok=True)

        self.root.title("click3 CPU 推理审核")
        self.root.geometry("+80+40")
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

        self.solver: Yolo4SiameseSolver | None = None

        self.header = tk.Label(root, font=("Microsoft YaHei UI", 12), anchor="w", justify="left")
        self.header.pack(fill="x", padx=10, pady=(8, 2))

        self.target_label = tk.Label(root, text="target", font=("Microsoft YaHei UI", 10))
        self.target_label.pack(fill="x", padx=10)

        self.canvas = tk.Canvas(root, bg="#202020", highlightthickness=0)
        self.canvas.pack(padx=10, pady=8)

        toolbar = tk.Frame(root)
        toolbar.pack(fill="x", padx=10, pady=(0, 8))
        self.infer_button = tk.Button(toolbar, text="推理", width=14, command=self.infer_current)
        self.infer_button.pack(side="left", padx=(0, 8))
        self.next_button = tk.Button(toolbar, text="下一个", width=14, command=self.next_sample)
        self.next_button.pack(side="left")

        self.footer = tk.Label(root, font=("Consolas", 10), anchor="w", justify="left")
        self.footer.pack(fill="x", padx=10, pady=(0, 8))

        self.root.bind("<Return>", lambda _event: self.infer_current())
        self.root.bind("<Right>", lambda _event: self.next_sample())
        self.root.bind("n", lambda _event: self.next_sample())
        self.root.bind("N", lambda _event: self.next_sample())

        self.load_current()

    @property
    def sample(self) -> Sample:
        return self.samples[self.current_index]

    def ensure_solver(self) -> Yolo4SiameseSolver:
        if self.solver is None:
            self.status_text = "正在加载 YOLO + Siamese CPU 模型..."
            self.redraw()
            self.root.update_idletasks()
            self.solver = Yolo4SiameseSolver(
                yolo_path=self.args.yolo,
                siamese_path=self.args.siamese,
                yolo_imgsz=self.args.imgsz,
                yolo_conf=self.args.yolo_conf,
                yolo_iou=self.args.yolo_iou,
                yolo_device="cpu",
                siamese_device="cpu",
                top_k=self.args.top_k,
                char_crop_size=self.args.char_crop_size,
            )
            self.solver.warmup()
        return self.solver

    def load_current(self) -> None:
        self.result = None
        self.elapsed_ms = None
        self.attempt_count = self.load_attempt_count(self.sample)
        self.status_text = f"点击“推理”开始 CPU 推理；当前样本已推理 {self.attempt_count} 次"

        self.bg_image = Image.open(self.sample.bg_path).convert("RGB")
        bg_w, bg_h = self.bg_image.size
        display_bg = self.bg_image.resize(
            (int(bg_w * self.args.scale), int(bg_h * self.args.scale)),
            Image.Resampling.NEAREST,
        )
        self.bg_photo = ImageTk.PhotoImage(display_bg)

        target_image = Image.open(self.sample.target_path).convert("RGB")
        target_scale = max(1, int(round(self.args.scale * 1.5)))
        target_image = target_image.resize(
            (target_image.width * target_scale, target_image.height * target_scale),
            Image.Resampling.NEAREST,
        )
        self.target_photo = ImageTk.PhotoImage(target_image)

        self.canvas.config(width=display_bg.width, height=display_bg.height)
        self.redraw()

    def redraw(self) -> None:
        self.canvas.delete("all")
        if self.bg_photo is not None:
            self.canvas.create_image(0, 0, image=self.bg_photo, anchor="nw")

        if self.result is not None:
            for index, (x, y) in enumerate(self.result.candidates, start=1):
                self.draw_candidate(index, x, y, self.result.candidate_confidences[index - 1])
            for index, (x, y) in enumerate(self.result.points, start=1):
                self.draw_point(index, x, y)

        elapsed = "" if self.elapsed_ms is None else f"  CPU耗时: {self.elapsed_ms:.1f} ms"
        self.header.config(
            text=f"{self.sample.name}  ({self.current_index + 1}/{len(self.samples)})  推理次数: {self.attempt_count}{elapsed}"
        )
        self.target_label.config(image=self.target_photo, compound="top", text="target image")
        self.footer.config(text=self.status_text)

    def draw_candidate(self, index: int, x: int, y: int, conf: float) -> None:
        sx = x * self.args.scale
        sy = y * self.args.scale
        half = max(20, int(30 * self.args.scale))
        color = "#ffb000"
        self.canvas.create_rectangle(sx - half, sy - half, sx + half, sy + half, outline=color, width=2)
        self.canvas.create_text(
            sx - half,
            sy - half - 18,
            text=f"C{index} {conf:.2f}",
            fill=color,
            font=("Consolas", 11, "bold"),
            anchor="nw",
        )

    def draw_point(self, index: int, x: int, y: int) -> None:
        color = POINT_COLORS.get(index, "#00d084")
        sx = x * self.args.scale
        sy = y * self.args.scale
        radius = max(8, int(6 * self.args.scale))
        self.canvas.create_oval(
            sx - radius,
            sy - radius,
            sx + radius,
            sy + radius,
            outline=color,
            width=max(3, int(2 * self.args.scale)),
        )
        self.canvas.create_text(
            sx + radius + 8,
            sy - radius,
            text=f"P{index}",
            fill=color,
            font=("Consolas", max(14, int(10 * self.args.scale)), "bold"),
            anchor="nw",
        )

    def infer_current(self) -> None:
        self.infer_button.config(state="disabled")
        self.next_button.config(state="disabled")
        attempt_index = self.attempt_count + 1
        self.status_text = f"CPU 第 {attempt_index} 次推理中..."
        self.redraw()
        self.root.update()

        try:
            solver = self.ensure_solver()
            start = time.perf_counter()
            raw_result = solver.solve(
                self.sample.target_path.read_bytes(),
                self.sample.bg_path.read_bytes(),
                return_details=True,
            )
            self.elapsed_ms = (time.perf_counter() - start) * 1000.0
            if not isinstance(raw_result, Yolo4SiameseResult):
                self.result = None
                self.attempt_count = attempt_index
                self.status_text = f"未得到有效预测，CPU耗时 {self.elapsed_ms:.1f} ms。可以再点推理重试。"
                self.save_attempt(None, 0.0, "no_prediction", attempt_index, None)
                return

            self.result = raw_result
            self.attempt_count = attempt_index
            margin = min_match_margin(raw_result)
            self.status_text = (
                f"第 {attempt_index} 次预测点: {raw_result.points}  候选框: {raw_result.candidates}  "
                f"min_margin={margin:.3f}  CPU耗时 {self.elapsed_ms:.1f} ms"
            )
            self.save_attempt(raw_result, margin, "ok", attempt_index, None)
        except Exception as exc:
            self.result = None
            self.elapsed_ms = None
            self.attempt_count = attempt_index
            self.status_text = f"第 {attempt_index} 次推理失败: {exc}"
            self.save_attempt(None, 0.0, "error", attempt_index, str(exc))
            messagebox.showerror("推理失败", str(exc))
        finally:
            self.infer_button.config(state="normal")
            self.next_button.config(state="normal")
            self.redraw()

    def prediction_path(self, sample: Sample) -> Path:
        return self.pred_dir / f"{sample.name}.json"

    def load_attempt_count(self, sample: Sample) -> int:
        output_path = self.prediction_path(sample)
        if not output_path.exists():
            return 0
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except Exception:
            return 0
        try:
            return int(payload.get("inference_count", 0))
        except Exception:
            return 0

    def load_existing_prediction(self) -> dict[str, Any]:
        output_path = self.prediction_path(self.sample)
        if not output_path.exists():
            return {}
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def save_attempt(
        self,
        result: Yolo4SiameseResult | None,
        margin: float,
        status: str,
        attempt_index: int,
        error: str | None,
    ) -> None:
        existing = self.load_existing_prediction()
        attempts = existing.get("attempts", [])
        if not isinstance(attempts, list):
            attempts = []

        points = result.points if result is not None else []
        candidates = result.candidates if result is not None else []
        confidences = result.candidate_confidences if result is not None else []
        matches = result.matches if result is not None else []
        similarity = result.similarity if result is not None else None

        attempt_payload = {
            "attempt": attempt_index,
            "status": status,
            "elapsed_ms": self.elapsed_ms,
            "points": points,
            "candidates": candidates,
            "candidate_confidences": [round(float(value), 6) for value in confidences],
            "matches": matches,
            "similarity": similarity,
            "min_margin": round(float(margin), 6),
            "error": error,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        attempts.append(attempt_payload)

        payload = {
            "sample": self.sample.name,
            "inference_count": attempt_index,
            "last_status": status,
            "elapsed_ms": self.elapsed_ms,
            "label": make_label_payload(self.sample, points),
            "points": points,
            "candidates": candidates,
            "candidate_confidences": [round(float(value), 6) for value in confidences],
            "matches": matches,
            "similarity": similarity,
            "min_margin": round(float(margin), 6),
            "attempts": attempts,
            "models": {
                "yolo": str(Path(self.args.yolo).resolve()),
                "siamese": str(Path(self.args.siamese).resolve()),
                "yolo_device": "cpu",
                "siamese_device": "cpu",
                "yolo_conf": self.args.yolo_conf,
                "top_k": self.args.top_k,
                "char_crop_size": self.args.char_crop_size,
            },
        }
        output_path = self.prediction_path(self.sample)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def next_sample(self) -> None:
        if self.current_index < len(self.samples) - 1:
            self.current_index += 1
            self.load_current()
        else:
            messagebox.showinfo("完成", "已经到最后一个样本。")


def main() -> None:
    args = parse_args()
    samples = find_samples(args.dataset, args.include_labeled)
    if not samples:
        raise SystemExit(f"No samples found in {args.dataset}")
    root = tk.Tk()
    InferenceReviewApp(root, args, samples)
    root.mainloop()


if __name__ == "__main__":
    main()
