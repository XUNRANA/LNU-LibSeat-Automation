from __future__ import annotations

import argparse
import csv
import json
import re
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageTk


SAMPLE_RE = re.compile(r"^sample_(\d{5})$")
CSV_FIELDS = [
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


@dataclass
class ReviewItem:
    sample: str
    status: str
    points: list[dict[str, int]]
    detail_path: Path
    vis_path: Path
    min_margin: float | None
    score_sum: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review click3 auto-label results and apply accepted labels.")
    parser.add_argument("--dataset", type=Path, default=Path("dataset/click3"))
    parser.add_argument("--auto-label-dir", type=Path, default=Path("runs/click3_auto_label/gpu_from_1001_posw3"))
    parser.add_argument("--start", type=int, default=1001, help="Start from sample number, for example 1001.")
    parser.add_argument("--include-labeled", action="store_true", default=True, help="Also review samples already having label.json.")
    parser.add_argument("--skip-labeled", action="store_true", help="Skip samples already having label.json.")
    parser.add_argument("--status", default="all", choices=("all", "ok", "need_rerun"))
    parser.add_argument("--max-width", type=int, default=1180)
    parser.add_argument("--max-height", type=int, default=760)
    return parser.parse_args()


def sample_index(sample: str) -> int:
    match = SAMPLE_RE.match(sample)
    return int(match.group(1)) if match else -1


def normalize_points(points: Any) -> list[dict[str, int]]:
    normalized: list[dict[str, int]] = []
    if not isinstance(points, list):
        return normalized
    for point in points[:3]:
        try:
            if isinstance(point, dict):
                x = point["x"]
                y = point["y"]
            else:
                x, y = point[0], point[1]
            normalized.append({"x": int(round(float(x))), "y": int(round(float(y)))})
        except Exception:
            continue
    return normalized


def label_payload(item: ReviewItem) -> dict[str, Any]:
    return {
        "sample": item.sample,
        "target_count": 3,
        "points": item.points,
        "bg": f"{item.sample}_bg.png",
        "target": f"{item.sample}_target.png",
    }


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


def compose_review_image(dataset: Path, item: ReviewItem) -> Image.Image:
    sample_dir = dataset / item.sample
    target = Image.open(sample_dir / f"{item.sample}_target.png").convert("RGB")
    bg = Image.open(sample_dir / f"{item.sample}_bg.png").convert("RGB")
    font = load_font(16)
    small_font = load_font(13)

    target_scale = 4
    target_big = target.resize((target.width * target_scale, target.height * target_scale), Image.Resampling.NEAREST)
    bg_gap = 14
    bottom_w = bg.width * 2 + bg_gap
    width = max(bottom_w, target_big.width, 560)
    header_h = 34
    target_h = target_big.height + 20
    gap = 12
    bg_y = header_h + target_h + gap
    label_h = 22
    height = bg_y + label_h + bg.height + 12
    image = Image.new("RGB", (width, height), (245, 246, 248))
    draw = ImageDraw.Draw(image)

    draw.rectangle([0, 0, width, header_h], fill=(25, 31, 38))
    draw.text((10, 8), item.sample, fill=(255, 255, 255), font=small_font)

    target_x = 10
    target_y = header_h + 10
    image.paste(target_big, (target_x, target_y))
    for index, (x1, x2) in enumerate(((5, 25), (25, 45), (45, 65)), start=1):
        box = [
            target_x + x1 * target_scale,
            target_y + 5 * target_scale,
            target_x + x2 * target_scale,
            target_y + 27 * target_scale,
        ]
        draw.rectangle(box, outline=(0, 128, 255), width=2)
        draw.text((box[0], max(target_y, box[1] - 16)), f"T{index}", fill=(0, 85, 180), font=small_font)

    draw.rectangle([0, bg_y, width, bg_y + 24], fill=(0, 0, 0))
    status_text = f"status={item.status}  score={item.score_sum}  margin={item.min_margin}"
    draw.text((8, bg_y + 4), status_text, fill=(255, 255, 255), font=small_font)

    panel_y = bg_y + label_h
    right_x = bg.width + bg_gap
    image.paste(bg, (0, panel_y))
    image.paste(bg, (right_x, panel_y))
    draw.text((8, panel_y + 4), "prediction", fill=(255, 255, 255), font=small_font)
    draw.text((right_x + 8, panel_y + 4), "original bg", fill=(255, 255, 255), font=small_font)

    for index, point in enumerate(item.points, start=1):
        x = int(point["x"])
        y = int(point["y"]) + panel_y
        color = (226, 62, 62)
        radius = 9
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], outline=color, width=3)
        draw.line([x - 13, y, x + 13, y], fill=color, width=2)
        draw.line([x, y - 13, x, y + 13], fill=color, width=2)
        label = f"P{index}"
        text_pos = (x + 13, y - 14)
        draw.text((text_pos[0] + 1, text_pos[1] + 1), label, fill=(255, 255, 255), font=font)
        draw.text(text_pos, label, fill=color, font=font)
    return image


def row_from_label(dataset: Path, sample: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    points = normalize_points(payload.get("points", []))
    if len(points) != 3:
        return None
    sample_dir = dataset / sample
    bg_path = sample_dir / payload.get("bg", f"{sample}_bg.png")
    target_path = sample_dir / payload.get("target", f"{sample}_target.png")
    if not bg_path.exists() or not target_path.exists():
        return None
    row: dict[str, Any] = {
        "sample": sample,
        "target_count": 3,
        "bg": str(bg_path.relative_to(dataset)),
        "target": str(target_path.relative_to(dataset)),
        "points_json": json.dumps(points, ensure_ascii=False),
    }
    for index, point in enumerate(points, start=1):
        row[f"T{index}_x"] = point["x"]
        row[f"T{index}_y"] = point["y"]
    return row


def build_existing_rows(dataset: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for sample_dir in sorted(dataset.glob("sample_*")):
        if not sample_dir.is_dir():
            continue
        label_path = sample_dir / "label.json"
        if not label_path.exists():
            continue
        try:
            payload = json.loads(label_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        row = row_from_label(dataset, sample_dir.name, payload)
        if row is not None:
            rows[sample_dir.name] = row
    return rows


def write_label_indexes(dataset: Path, rows_by_sample: dict[str, dict[str, Any]]) -> None:
    rows = [rows_by_sample[key] for key in sorted(rows_by_sample, key=sample_index)]
    csv_path = dataset / "labels.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    labels_json = {row["sample"]: row for row in rows}
    (dataset / "labels.json").write_text(json.dumps(labels_json, ensure_ascii=False, indent=2), encoding="utf-8")


def load_review_items(args: argparse.Namespace) -> list[ReviewItem]:
    manifest_path = args.auto_label_dir / "manifest.csv"
    if not manifest_path.exists():
        raise SystemExit(f"manifest not found: {manifest_path}")

    items: list[ReviewItem] = []
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            sample = row["sample"]
            if args.start is not None and sample_index(sample) < args.start:
                continue
            if args.status != "all" and row.get("status") != args.status:
                continue
            sample_dir = args.dataset / sample
            if getattr(args, "skip_labeled", False) and (sample_dir / "label.json").exists():
                continue

            detail_path = Path(row["detail_path"])
            vis_path = Path(row["vis_path"])
            if not vis_path.exists():
                continue
            points = normalize_points(json.loads(row.get("points") or "[]"))
            if len(points) != 3:
                continue
            try:
                min_margin = float(row["min_margin"]) if row.get("min_margin") not in (None, "") else None
            except Exception:
                min_margin = None
            try:
                score_sum = float(row["score_sum"]) if row.get("score_sum") not in (None, "") else None
            except Exception:
                score_sum = None
            items.append(
                ReviewItem(
                    sample=sample,
                    status=str(row.get("status", "")),
                    points=points,
                    detail_path=detail_path,
                    vis_path=vis_path,
                    min_margin=min_margin,
                    score_sum=score_sum,
                )
            )
    return items


class ReviewApp:
    def __init__(self, root: tk.Tk, args: argparse.Namespace, items: list[ReviewItem]) -> None:
        self.root = root
        self.args = args
        self.items = items
        self.index = 0
        self.rows_by_sample = build_existing_rows(args.dataset)
        self.accepted_this_session = 0
        self.rejected_this_session = 0
        self.photo: ImageTk.PhotoImage | None = None

        self.root.title("click3 自动标注审核")
        self.root.geometry("+70+30")

        self.header = tk.Label(root, font=("Microsoft YaHei UI", 12), anchor="w", justify="left")
        self.header.pack(fill="x", padx=10, pady=(8, 4))

        self.image_label = tk.Label(root, bg="#202020")
        self.image_label.pack(padx=10, pady=6)

        toolbar = tk.Frame(root)
        toolbar.pack(fill="x", padx=10, pady=(4, 8))
        self.success_button = tk.Button(toolbar, text="成功", width=16, command=self.accept_current)
        self.success_button.pack(side="left", padx=(0, 8))
        self.fail_button = tk.Button(toolbar, text="失败", width=16, command=self.reject_current)
        self.fail_button.pack(side="left", padx=(0, 8))
        self.prev_button = tk.Button(toolbar, text="上一个", width=16, command=self.prev_item)
        self.prev_button.pack(side="left", padx=(0, 8))
        self.next_button = tk.Button(toolbar, text="下一个", width=16, command=self.next_item)
        self.next_button.pack(side="left")

        self.footer = tk.Label(root, font=("Consolas", 10), anchor="w", justify="left")
        self.footer.pack(fill="x", padx=10, pady=(0, 8))

        self.root.bind("<Return>", lambda _event: self.accept_current())
        self.root.bind("s", lambda _event: self.accept_current())
        self.root.bind("S", lambda _event: self.accept_current())
        self.root.bind("f", lambda _event: self.reject_current())
        self.root.bind("F", lambda _event: self.reject_current())
        self.root.bind("<Right>", lambda _event: self.next_item())
        self.root.bind("<Left>", lambda _event: self.prev_item())
        self.root.bind("n", lambda _event: self.next_item())
        self.root.bind("N", lambda _event: self.next_item())
        self.root.bind("p", lambda _event: self.prev_item())
        self.root.bind("P", lambda _event: self.prev_item())

        self.load_current()

    @property
    def current(self) -> ReviewItem:
        return self.items[self.index]

    def load_current(self) -> None:
        if not self.items:
            self.header.config(text="没有待审核样本")
            self.footer.config(text="")
            self.success_button.config(state="disabled")
            self.fail_button.config(state="disabled")
            self.next_button.config(state="disabled")
            return

        item = self.current
        image = compose_review_image(self.args.dataset, item)
        image = ImageOps.contain(image, (self.args.max_width, self.args.max_height), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image)
        self.image_label.config(image=self.photo)

        self.header.config(
            text=(
                f"{item.sample}  ({self.index + 1}/{len(self.items)})  "
                f"status={item.status}  points={item.points}"
            )
        )
        self.footer.config(
            text=(
                f"min_margin={item.min_margin}  score_sum={item.score_sum}  "
                f"本次成功: {self.accepted_this_session}  "
                f"本次失败撤销: {self.rejected_this_session}  "
                f"已索引标签: {len(self.rows_by_sample)}"
            )
        )

    def accept_current(self) -> None:
        item = self.current
        sample_dir = self.args.dataset / item.sample
        if not sample_dir.exists():
            messagebox.showerror("错误", f"样本目录不存在: {sample_dir}")
            return
        payload = label_payload(item)
        label_path = sample_dir / "label.json"
        label_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        row = row_from_label(self.args.dataset, item.sample, payload)
        if row is None:
            messagebox.showerror("错误", f"无法更新 labels.csv/json: {item.sample}")
            return
        self.rows_by_sample[item.sample] = row
        write_label_indexes(self.args.dataset, self.rows_by_sample)

        self.accepted_this_session += 1
        self.next_item()

    def reject_current(self) -> None:
        item = self.current
        sample_dir = self.args.dataset / item.sample
        label_path = sample_dir / "label.json"
        if label_path.exists():
            label_path.unlink()
        self.rows_by_sample.pop(item.sample, None)
        write_label_indexes(self.args.dataset, self.rows_by_sample)

        self.rejected_this_session += 1
        self.next_item()

    def next_item(self) -> None:
        if self.index < len(self.items) - 1:
            self.index += 1
            self.load_current()
        else:
            messagebox.showinfo("完成", "已经到最后一个待审核样本。")

    def prev_item(self) -> None:
        if self.index > 0:
            self.index -= 1
            self.load_current()
        else:
            messagebox.showinfo("提示", "已经是第一个待审核样本。")


def main() -> None:
    args = parse_args()
    items = load_review_items(args)
    if not items:
        raise SystemExit("No review items found.")
    root = tk.Tk()
    ReviewApp(root, args, items)
    root.mainloop()


if __name__ == "__main__":
    main()
