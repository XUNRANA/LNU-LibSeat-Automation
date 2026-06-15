from __future__ import annotations

import argparse
import csv
import json
import re
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, simpledialog
from typing import Any

from PIL import Image, ImageTk


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
    modal_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual annotation tool for click3 captcha dataset.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("dataset/click3"),
        help="Dataset root containing sample_00001 style folders.",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=2.0,
        help="Display scale for the bg image. Saved coordinates remain original pixels.",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=None,
        help="Start from sample number, for example --start 105.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only print dataset/label stats; do not open the GUI.",
    )
    parser.add_argument(
        "--first-unlabeled",
        action="store_true",
        help="Open the GUI at the first sample without a complete label.",
    )
    parser.add_argument(
        "--import-eval",
        action="store_true",
        help="Import eval_p0_ddddocr_failures/annotations_by_sample.csv into per-sample label.json files, then exit.",
    )
    parser.add_argument(
        "--eval-csv",
        type=Path,
        default=None,
        help="CSV to import when --import-eval is used. Defaults to dataset/click3/eval_p0_ddddocr_failures/annotations_by_sample.csv.",
    )
    parser.add_argument(
        "--overwrite-labels",
        action="store_true",
        help="Overwrite existing sample label.json files when importing eval annotations.",
    )
    return parser.parse_args()


def find_samples(dataset: Path) -> list[Sample]:
    samples: list[Sample] = []
    for folder in sorted(dataset.iterdir()):
        if not folder.is_dir():
            continue
        match = SAMPLE_RE.match(folder.name)
        if not match:
            continue
        sample_no = match.group(1)
        bg_path = folder / f"{folder.name}_bg.png"
        target_path = folder / f"{folder.name}_target.png"
        modal_path = folder / f"{folder.name}_modal.png"
        if bg_path.exists() and target_path.exists():
            samples.append(
                Sample(
                    name=folder.name,
                    index=int(sample_no),
                    folder=folder,
                    bg_path=bg_path,
                    target_path=target_path,
                    modal_path=modal_path,
                )
            )
    return samples


def label_path(sample: Sample) -> Path:
    return sample.folder / "label.json"


def load_label(sample: Sample) -> dict[str, Any]:
    path = label_path(sample)
    if not path.exists():
        return {"target_count": 3, "points": []}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {"target_count": 3, "points": []}
    points = data.get("points", [])
    return {
        "target_count": int(data.get("target_count") or max(len(points), 1) or 3),
        "points": points if isinstance(points, list) else [],
    }


def normalize_points(points: list[dict[str, Any]], target_count: int) -> list[dict[str, int]]:
    normalized: list[dict[str, int]] = []
    for point in points[:target_count]:
        try:
            x = int(round(float(point["x"])))
            y = int(round(float(point["y"])))
        except Exception:
            continue
        normalized.append({"x": x, "y": y})
    return normalized


def save_label(sample: Sample, target_count: int, points: list[dict[str, int]]) -> None:
    payload = {
        "sample": sample.name,
        "target_count": target_count,
        "points": normalize_points(points, target_count),
        "bg": sample.bg_path.name,
        "target": sample.target_path.name,
    }
    with label_path(sample).open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def export_labels(dataset: Path, samples: list[Sample]) -> tuple[Path, Path]:
    rows: list[dict[str, Any]] = []
    labels: dict[str, Any] = {}
    for sample in samples:
        data = load_label(sample)
        points = normalize_points(data["points"], int(data["target_count"]))
        if len(points) != int(data["target_count"]):
            continue

        row: dict[str, Any] = {
            "sample": sample.name,
            "target_count": int(data["target_count"]),
            "bg": str(sample.bg_path.relative_to(dataset)),
            "target": str(sample.target_path.relative_to(dataset)),
        }
        for index in range(1, 4):
            if index <= len(points):
                row[f"T{index}_x"] = points[index - 1]["x"]
                row[f"T{index}_y"] = points[index - 1]["y"]
            else:
                row[f"T{index}_x"] = ""
                row[f"T{index}_y"] = ""
        row["points_json"] = json.dumps(points, ensure_ascii=False)
        rows.append(row)
        labels[sample.name] = row

    csv_path = dataset / "labels.csv"
    json_path = dataset / "labels.json"
    fieldnames = [
        "sample",
        "target_count",
        "T1_x",
        "T1_y",
        "T2_x",
        "T2_y",
        "T3_x",
        "T3_y",
        "bg",
        "target",
        "points_json",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(labels, fh, ensure_ascii=False, indent=2)
    return csv_path, json_path


def import_eval_annotations(
    dataset: Path,
    samples: list[Sample],
    eval_csv: Path,
    overwrite: bool,
) -> tuple[int, int, int]:
    sample_by_id = {f"{sample.index:05d}": sample for sample in samples}
    imported = 0
    skipped_existing = 0
    skipped_invalid = 0

    with eval_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            sample_id = row.get("sample_id", "")
            sample = sample_by_id.get(sample_id)
            if sample is None:
                skipped_invalid += 1
                continue
            if label_path(sample).exists() and not overwrite:
                skipped_existing += 1
                continue

            try:
                target_count = int(row["target_count"])
            except Exception:
                skipped_invalid += 1
                continue
            if target_count not in (1, 2, 3):
                skipped_invalid += 1
                continue

            points: list[dict[str, int]] = []
            for index in range(1, target_count + 1):
                try:
                    x = int(round(float(row[f"T{index}_x"])))
                    y = int(round(float(row[f"T{index}_y"])))
                except Exception:
                    skipped_invalid += 1
                    points = []
                    break
                points.append({"x": x, "y": y})
            if len(points) != target_count:
                continue

            save_label(sample, target_count, points)
            imported += 1

    export_labels(dataset, samples)
    return imported, skipped_existing, skipped_invalid


class AnnotatorApp:
    def __init__(
        self,
        root: tk.Tk,
        dataset: Path,
        samples: list[Sample],
        scale: float,
        start: int | None,
        first_unlabeled: bool,
    ):
        self.root = root
        self.dataset = dataset
        self.samples = samples
        self.scale = scale
        self.current_index = 0
        self.target_count = 3
        self.points: list[dict[str, int]] = []
        self.dirty = False
        self.bg_image: Image.Image | None = None
        self.bg_photo: ImageTk.PhotoImage | None = None
        self.target_photo: ImageTk.PhotoImage | None = None

        if start is not None:
            for index, sample in enumerate(samples):
                if sample.index >= start:
                    self.current_index = index
                    break
        elif first_unlabeled:
            for index, sample in enumerate(samples):
                if not self.is_complete(sample):
                    self.current_index = index
                    break

        self.root.title("click3 manual annotator")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.header = tk.Label(root, font=("Microsoft YaHei UI", 12), anchor="w", justify="left")
        self.header.pack(fill="x", padx=10, pady=(8, 2))

        self.target_label = tk.Label(root, text="target", font=("Microsoft YaHei UI", 10))
        self.target_label.pack(fill="x", padx=10)

        self.canvas = tk.Canvas(root, bg="#202020", highlightthickness=0)
        self.canvas.pack(padx=10, pady=8)
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Button-3>", self.undo)

        self.footer = tk.Label(root, font=("Consolas", 10), anchor="w", justify="left")
        self.footer.pack(fill="x", padx=10, pady=(0, 8))

        self.bind_keys()
        self.load_current()

    def bind_keys(self) -> None:
        self.root.bind("<Return>", lambda _event: self.save_and_next())
        self.root.bind("s", lambda _event: self.save_and_next())
        self.root.bind("S", lambda _event: self.save_and_next())
        self.root.bind("a", lambda _event: self.prev_sample())
        self.root.bind("A", lambda _event: self.prev_sample())
        self.root.bind("d", lambda _event: self.next_sample())
        self.root.bind("D", lambda _event: self.next_sample())
        self.root.bind("n", lambda _event: self.next_sample())
        self.root.bind("N", lambda _event: self.next_sample())
        self.root.bind("<Right>", lambda _event: self.next_sample())
        self.root.bind("p", lambda _event: self.prev_sample())
        self.root.bind("P", lambda _event: self.prev_sample())
        self.root.bind("<Left>", lambda _event: self.prev_sample())
        self.root.bind("z", self.undo)
        self.root.bind("Z", self.undo)
        self.root.bind("<BackSpace>", self.undo)
        self.root.bind("c", lambda _event: self.clear_points())
        self.root.bind("C", lambda _event: self.clear_points())
        self.root.bind("g", lambda _event: self.go_to_sample())
        self.root.bind("G", lambda _event: self.go_to_sample())
        self.root.bind("u", lambda _event: self.next_unlabeled())
        self.root.bind("U", lambda _event: self.next_unlabeled())
        self.root.bind("1", lambda _event: self.set_target_count(1))
        self.root.bind("2", lambda _event: self.set_target_count(2))
        self.root.bind("3", lambda _event: self.set_target_count(3))

    @property
    def sample(self) -> Sample:
        return self.samples[self.current_index]

    def load_current(self) -> None:
        sample = self.sample
        data = load_label(sample)
        self.target_count = min(max(int(data["target_count"]), 1), 3)
        self.points = normalize_points(data["points"], self.target_count)
        self.dirty = False

        self.bg_image = Image.open(sample.bg_path).convert("RGB")
        bg_w, bg_h = self.bg_image.size
        display_bg = self.bg_image.resize(
            (int(bg_w * self.scale), int(bg_h * self.scale)),
            Image.Resampling.NEAREST,
        )
        self.bg_photo = ImageTk.PhotoImage(display_bg)

        target_image = Image.open(sample.target_path).convert("RGB")
        target_scale = max(1, int(round(self.scale * 1.5)))
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

        for index, point in enumerate(self.points, start=1):
            self.draw_point(index, point["x"], point["y"])

        labeled_count = sum(1 for sample in self.samples if self.is_complete(sample))
        self.header.config(
            text=(
                f"{self.sample.name}  ({self.current_index + 1}/{len(self.samples)})  "
                f"已标注 {labeled_count}/{len(self.samples)}  "
                f"目标数: {self.target_count}  当前点数: {len(self.points)}"
            )
        )
        self.target_label.config(image=self.target_photo, compound="top", text="target image")
        self.footer.config(
            text=(
                "左键添加点 | 右键/Z/Backspace撤销 | 1/2/3设置目标数 | "
                "Enter保存并下一张 | S保存 | ←/→上一张下一张 | C清空 | G跳转 | U下个未标注"
            )
        )

    def draw_point(self, index: int, x: int, y: int) -> None:
        color = POINT_COLORS.get(index, "#00d084")
        sx = x * self.scale
        sy = y * self.scale
        radius = max(7, int(5 * self.scale))
        self.canvas.create_oval(
            sx - radius,
            sy - radius,
            sx + radius,
            sy + radius,
            outline=color,
            width=max(2, int(2 * self.scale)),
        )
        self.canvas.create_text(
            sx + radius + 10,
            sy - radius - 2,
            text=f"T{index}",
            fill=color,
            font=("Consolas", max(13, int(9 * self.scale)), "bold"),
            anchor="nw",
        )

    def on_click(self, event: tk.Event) -> None:
        if self.bg_image is None:
            return
        bg_w, bg_h = self.bg_image.size
        x = min(max(int(round(event.x / self.scale)), 0), bg_w - 1)
        y = min(max(int(round(event.y / self.scale)), 0), bg_h - 1)
        if len(self.points) >= self.target_count:
            self.points = []
        self.points.append({"x": x, "y": y})
        self.dirty = True
        self.redraw()

    def undo(self, _event: tk.Event | None = None) -> None:
        if self.points:
            self.points.pop()
            self.dirty = True
            self.redraw()

    def clear_points(self) -> None:
        self.points = []
        self.dirty = True
        self.redraw()

    def set_target_count(self, count: int) -> None:
        self.target_count = count
        self.points = self.points[:count]
        self.dirty = True
        self.redraw()

    def save_current(self, show_message: bool = False) -> bool:
        if len(self.points) != self.target_count:
            messagebox.showwarning(
                "点数不完整",
                f"{self.sample.name} 需要 {self.target_count} 个点，现在只有 {len(self.points)} 个。",
            )
            return False
        save_label(self.sample, self.target_count, self.points)
        export_labels(self.dataset, self.samples)
        self.dirty = False
        if show_message:
            messagebox.showinfo("已保存", f"{self.sample.name} 已保存。")
        return True

    def save_and_next(self) -> None:
        if self.save_current(show_message=False):
            self.next_sample()

    def next_sample(self) -> None:
        if not self.confirm_unsaved_change():
            return
        if self.current_index < len(self.samples) - 1:
            self.current_index += 1
            self.load_current()

    def prev_sample(self) -> None:
        if not self.confirm_unsaved_change():
            return
        if self.current_index > 0:
            self.current_index -= 1
            self.load_current()

    def go_to_sample(self) -> None:
        if not self.confirm_unsaved_change():
            return
        value = simpledialog.askinteger("跳转", "输入样例编号，例如 105：", parent=self.root)
        if value is None:
            return
        for index, sample in enumerate(self.samples):
            if sample.index == value:
                self.current_index = index
                self.load_current()
                return
        messagebox.showwarning("不存在", f"找不到 sample_{value:05d}")

    def next_unlabeled(self) -> None:
        if not self.confirm_unsaved_change():
            return
        for index in range(self.current_index + 1, len(self.samples)):
            if not self.is_complete(self.samples[index]):
                self.current_index = index
                self.load_current()
                return
        for index in range(0, self.current_index + 1):
            if not self.is_complete(self.samples[index]):
                self.current_index = index
                self.load_current()
                return
        messagebox.showinfo("完成", "没有未标注样例。")

    def is_complete(self, sample: Sample) -> bool:
        data = load_label(sample)
        return len(normalize_points(data["points"], int(data["target_count"]))) == int(data["target_count"])

    def confirm_unsaved_change(self) -> bool:
        if not self.dirty:
            return True
        if len(self.points) == self.target_count:
            answer = messagebox.askyesnocancel(
                "未保存",
                f"{self.sample.name} 已经点完但还没保存。是否先保存？",
            )
            if answer is None:
                return False
            if answer:
                return self.save_current(show_message=False)
            return True

        return messagebox.askokcancel(
            "未保存",
            f"{self.sample.name} 当前点数不完整，离开会丢弃当前修改。继续？",
        )

    def on_close(self) -> None:
        if not self.confirm_unsaved_change():
            return
        export_labels(self.dataset, self.samples)
        self.root.destroy()


def print_stats(dataset: Path, samples: list[Sample]) -> None:
    complete = 0
    incomplete = 0
    for sample in samples:
        data = load_label(sample)
        points = normalize_points(data["points"], int(data["target_count"]))
        if len(points) == int(data["target_count"]):
            complete += 1
        else:
            incomplete += 1
    print(f"dataset: {dataset}")
    print(f"samples: {len(samples)}")
    print(f"complete labels: {complete}")
    print(f"incomplete labels: {incomplete}")
    print(f"outputs: {dataset / 'labels.csv'}, {dataset / 'labels.json'}")


def main() -> None:
    args = parse_args()
    dataset = args.dataset.resolve()
    if not dataset.exists():
        raise SystemExit(f"dataset not found: {dataset}")

    samples = find_samples(dataset)
    if not samples:
        raise SystemExit(f"no sample_00001 style folders found in: {dataset}")

    if args.check:
        print_stats(dataset, samples)
        return

    if args.import_eval:
        eval_csv = (
            args.eval_csv.resolve()
            if args.eval_csv
            else dataset / "eval_p0_ddddocr_failures" / "annotations_by_sample.csv"
        )
        if not eval_csv.exists():
            raise SystemExit(f"eval annotations csv not found: {eval_csv}")
        imported, skipped_existing, skipped_invalid = import_eval_annotations(
            dataset,
            samples,
            eval_csv,
            args.overwrite_labels,
        )
        print(f"imported labels: {imported}")
        print(f"skipped existing: {skipped_existing}")
        print(f"skipped invalid: {skipped_invalid}")
        print(f"outputs: {dataset / 'labels.csv'}, {dataset / 'labels.json'}")
        return

    root = tk.Tk()
    AnnotatorApp(root, dataset, samples, args.scale, args.start, args.first_unlabeled)
    root.mainloop()


if __name__ == "__main__":
    main()
