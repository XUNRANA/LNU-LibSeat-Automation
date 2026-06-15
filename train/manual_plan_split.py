"""
手动标注 target 字符分割点工具 — 6 条线 (4 竖 + 2 横)。

用法:
  python manual_plan_split.py --force
  python manual_plan_split.py --resume --scale 5

操作:
  - A/D 左右/上下移动当前线 (竖线左右, 横线上下)
  - Tab 切换选中的线 (S1→S2→S3→S4→S5→S6)
  - S/Enter 保存并下一张
  - ← → 翻页
  - Q 退出

线序:
  S1(红)=左边界  S2(绿)=分割1  S3(黄)=分割2  S4(红)=右边界  S5(蓝)=上边界  S6(蓝)=下边界
"""

import argparse
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import numpy as np
from PIL import Image, ImageTk

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "dataset" / "click3"
SAVE_PATH = PROJECT_ROOT / "dataset" / "manual_splits.json"

# 6 条线颜色
POINT_COLORS = {1: "#ff4d6d", 2: "#00d084", 3: "#ffb000", 4: "#ff4d6d", 5: "#4da6ff", 6: "#4da6ff"}
AUTO_LINE_COLOR = "#555555"


def get_test_samples(n: int = 100) -> list[str]:
    labels = json.loads((DATA_DIR / "labels.json").read_text(encoding="utf-8"))
    all_samples = {k: v for k, v in labels.items() if v.get("target_count") == 3}

    from siamese_dataloader_v8 import discover_folders, split_folders

    folders = discover_folders(str(PROJECT_ROOT / "dataset" / "click3_siamese"))
    _, val_folders = split_folders(folders, train_ratio=0.9, seed=42)

    val_names = set()
    for f in val_folders:
        val_names.add(f["folder"].replace("\\", "/").split("/")[-1])

    siamese_existing = set()
    for f in folders:
        siamese_existing.add(f["folder"].replace("\\", "/").split("/")[-1])
    new_names = set(k for k in all_samples if k not in siamese_existing)

    combined = sorted(val_names | new_names)
    valid = [s for s in combined if (DATA_DIR / s / f"{s}_target.png").exists()]
    return valid[:n]


def load_splits() -> dict:
    if SAVE_PATH.exists():
        return json.loads(SAVE_PATH.read_text(encoding="utf-8"))
    return {}


def save_splits(splits: dict) -> None:
    SAVE_PATH.write_text(json.dumps(splits, ensure_ascii=False, indent=2), encoding="utf-8")


def compute_auto_splits(target_path: Path) -> dict:
    """返回 6 条线: x1, x2, x3, x4 (竖), y1, y2 (横)。"""
    arr = np.array(Image.open(target_path).convert("L"))
    mask = arr < 245
    # 竖直方向
    xs = np.where(mask.any(axis=0))[0]
    if len(xs) == 0:
        fx1, fx2 = 0, arr.shape[1]
    else:
        fx1, fx2 = int(xs[0]), int(xs[-1]) + 1
    content_w = fx2 - fx1
    s1 = int(round(fx1 + content_w / 3))
    s2 = int(round(fx1 + 2 * content_w / 3))
    # 水平方向
    ys = np.where(mask.any(axis=1))[0]
    if len(ys) == 0:
        fy1, fy2 = 0, arr.shape[0]
    else:
        fy1, fy2 = int(ys[0]), int(ys[-1]) + 1
    return {"x1": fx1, "x2": s1, "x3": s2, "x4": fx2, "y1": fy1, "y2": fy2}


class App:
    def __init__(self, root: tk.Tk, samples: list[str], scale: float, resume: bool, force: bool = False):
        self.root = root
        self.samples = samples
        self.scale = scale
        self.idx = 0
        self.selected = 0  # 0-5 → S1-S6
        # points: [x1, x2, x3, x4, y1, y2]
        self.points = [0, 0, 0, 0, 0, 0]
        self.dirty = False
        self.splits = {} if force else load_splits()

        if resume:
            for i, s in enumerate(samples):
                if s not in self.splits:
                    self.idx = i
                    break

        self.root.title("Plan Split Annotator")
        self.root.configure(bg="#1e1e1e")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.resizable(False, False)

        # Header
        self.header = tk.Label(root, font=("Consolas", 11), anchor="w", bg="#1e1e1e", fg="#cccccc")
        self.header.pack(fill="x", padx=10, pady=(8, 2))

        # Canvas
        self.canvas = tk.Canvas(root, bg="#2d2d2d", highlightthickness=0)
        self.canvas.pack(padx=10, pady=4)

        # Preview row
        self.preview_frame = tk.Frame(root, bg="#1e1e1e")
        self.preview_frame.pack(padx=10, pady=4)
        self.preview_labels: list[tk.Label] = []
        self._photos: list[ImageTk.PhotoImage] = []
        for i in range(3):
            lbl = tk.Label(self.preview_frame, text=f"P{i+1}", bg="#1e1e1e", fg="#cccccc",
                           font=("Consolas", 10), compound="top")
            lbl.pack(side="left", padx=8)
            self.preview_labels.append(lbl)

        # Footer
        self.footer = tk.Label(root, font=("Consolas", 9), anchor="w", bg="#1e1e1e", fg="#999999")
        self.footer.pack(fill="x", padx=10, pady=(0, 8))

        self._bind_keys()
        self.load_current()

    def _bind_keys(self):
        self.root.bind("a", lambda _: self.move(-1))
        self.root.bind("A", lambda _: self.move(-1))
        self.root.bind("d", lambda _: self.move(1))
        self.root.bind("D", lambda _: self.move(1))
        self.root.bind("<Tab>", self.switch_line)
        self.root.bind("<Return>", lambda _: self.save_and_next())
        self.root.bind("s", lambda _: self.save_and_next())
        self.root.bind("S", lambda _: self.save_and_next())
        self.root.bind("<Right>", lambda _: self.next_sample())
        self.root.bind("<Left>", lambda _: self.prev_sample())
        self.root.bind("q", lambda _: self.on_close())
        self.root.bind("Q", lambda _: self.on_close())

    def load_current(self):
        name = self.samples[self.idx]
        path = DATA_DIR / name / f"{name}_target.png"

        try:
            self.img = Image.open(path).convert("RGB")
        except Exception as e:
            messagebox.showerror("错误", f"无法加载 {path}: {e}")
            return

        w, h = self.img.size
        sw, sh = int(w * self.scale), int(h * self.scale)
        display = self.img.resize((sw, sh), Image.Resampling.NEAREST)
        self._display_photo = ImageTk.PhotoImage(display)
        self.canvas.config(width=sw, height=sh)

        # Load saved or auto splits
        if name in self.splits:
            s = self.splits[name]
            self.points = [s["x1"], s["x2"], s["x3"], s["x4"], s["y1"], s["y2"]]
        else:
            auto = compute_auto_splits(path)
            self.points = [auto["x1"], auto["x2"], auto["x3"], auto["x4"], auto["y1"], auto["y2"]]
        self.dirty = False
        self.selected = 0
        self.redraw()

    def redraw(self):
        self.canvas.delete("all")
        name = self.samples[self.idx]
        w, h = self.img.size
        sw, sh = int(w * self.scale), int(h * self.scale)

        self.canvas.create_image(0, 0, image=self._display_photo, anchor="nw")

        # Auto split reference (gray dashed)
        try:
            auto = compute_auto_splits(DATA_DIR / name / f"{name}_target.png")
            # 竖线
            for ax in (auto["x1"], auto["x2"], auto["x3"], auto["x4"]):
                sx = ax * self.scale
                for yy in range(0, sh, 8):
                    self.canvas.create_line(sx, yy, sx, min(yy + 4, sh), fill=AUTO_LINE_COLOR)
            # 横线
            for ay in (auto["y1"], auto["y2"]):
                sy = ay * self.scale
                for xx in range(0, sw, 8):
                    self.canvas.create_line(xx, sy, min(xx + 4, sw), sy, fill=AUTO_LINE_COLOR)
        except Exception:
            pass

        # Manual lines: S1-S4 竖线, S5-S6 横线
        for i in range(6):
            color = POINT_COLORS.get(i + 1, "#ffffff")
            is_selected = (i == self.selected)
            width = 3 if is_selected else 2
            val = self.points[i]

            if i < 4:  # 竖线
                sx = val * self.scale
                self.canvas.create_line(sx, 0, sx, sh, fill=color, width=width)
                label = f"S{i+1}={val}" + (" ◄" if is_selected else "")
                self.canvas.create_text(sx + 5, 5 + i * 18, text=label, fill=color,
                                        font=("Consolas", 10, "bold" if is_selected else "normal"), anchor="nw")
            else:  # 横线
                sy = val * self.scale
                self.canvas.create_line(0, sy, sw, sy, fill=color, width=width)
                label = f"S{i+1}={val}" + (" ◄" if is_selected else "")
                self.canvas.create_text(5, sy + 3 + (i - 4) * 16, text=label, fill=color,
                                        font=("Consolas", 10, "bold" if is_selected else "normal"), anchor="nw")

        # Shade 3 regions between S1-S2-S3-S4, clipped to S5-S6
        x1, x2, x3, x4, y1, y2 = self.points
        if x1 < x2 < x3 < x4 and y1 < y2:
            regions = [(x1, x2), (x2, x3), (x3, x4)]
            for idx_r, (rx1, rx2) in enumerate(regions):
                sx1, sx2 = int(rx1 * self.scale), int(rx2 * self.scale)
                sy1, sy2 = int(y1 * self.scale), int(y2 * self.scale)
                color = POINT_COLORS.get(idx_r + 2, "#ffffff")
                self.canvas.create_rectangle(sx1, sy1, sx2, sy2, outline=color, width=1, dash=(4, 4))
                self.canvas.create_text((sx1 + sx2) // 2, (sy1 + sy2) // 2, text=f"P{idx_r+1}",
                                        fill=color, font=("Consolas", 14, "bold"))

        # Header
        labeled = sum(1 for s in self.samples if s in self.splits)
        self.header.config(text=f"{name}  ({self.idx+1}/{len(self.samples)})  "
                                f"已标注 {labeled}/{len(self.samples)}  "
                                f"x=[{x1},{x2},{x3},{x4}] y=[{y1},{y2}]")
        self.footer.config(text="A/D移动 | Tab切换(S1→S2→S3→S4→S5→S6) | S/Enter保存 | ←→翻页 | Q退出")

        self._update_previews()

    def _update_previews(self):
        self._photos.clear()
        w, h = self.img.size
        x1, x2, x3, x4, y1, y2 = self.points
        if x1 < x2 < x3 < x4 and y1 < y2:
            regions = [(x1, x2), (x2, x3), (x3, x4)]
            crop_top, crop_bot = y1, y2
        else:
            regions = [(0, w // 3), (w // 3, 2 * w // 3), (2 * w // 3, w)]
            crop_top, crop_bot = 0, h

        for i, (rx1, rx2) in enumerate(regions):
            crop = self.img.crop((rx1, crop_top, max(rx1 + 1, rx2), crop_bot))
            disp = crop.resize((80, 80), Image.Resampling.NEAREST)
            photo = ImageTk.PhotoImage(disp)
            self._photos.append(photo)
            self.preview_labels[i].config(image=photo, text=f"P{i+1} [{rx1}:{rx2}]")

    def move(self, delta):
        i = self.selected
        if i < 4:
            # 竖线: 左右移动, 限制在图片宽度内
            limit = self.img.size[0]
        else:
            # 横线: 上下移动, 限制在图片高度内
            limit = self.img.size[1]
        new_val = max(0, min(limit - 1, self.points[i] + delta))
        self.points[i] = new_val
        self.dirty = True
        self.redraw()

    def switch_line(self, _=None):
        self.selected = (self.selected + 1) % 6
        self.redraw()

    def _save(self) -> bool:
        x1, x2, x3, x4, y1, y2 = self.points
        if not (x1 < x2 < x3 < x4):
            messagebox.showwarning("错误", "S1 < S2 < S3 < S4 (竖线) 必须严格递增")
            return False
        if not (y1 < y2):
            messagebox.showwarning("错误", "S5 < S6 (横线) 必须严格递增")
            return False
        self.splits[self.samples[self.idx]] = {
            "x1": x1, "x2": x2, "x3": x3, "x4": x4, "y1": y1, "y2": y2
        }
        save_splits(self.splits)
        self.dirty = False
        return True

    def save_and_next(self):
        if self._save():
            self.next_sample()

    def next_sample(self):
        if self.dirty:
            if messagebox.askyesnocancel("未保存", "保存？"):
                if not self._save():
                    return
            elif messagebox.askyesnocancel("未保存", "保存？") is None:
                return
        if self.idx < len(self.samples) - 1:
            self.idx += 1
            self.load_current()

    def prev_sample(self):
        if self.dirty:
            if not messagebox.askokcancel("未保存", "丢弃？"):
                return
        if self.idx > 0:
            self.idx -= 1
            self.load_current()

    def on_close(self):
        if self.dirty:
            if messagebox.askyesnocancel("退出", "保存？"):
                self._save()
            elif messagebox.askyesnocancel("退出", "保存？") is None:
                return
        save_splits(self.splits)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", nargs="*", default=None)
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--scale", type=float, default=5.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true", help="Ignore saved splits, annotate all from scratch.")
    args = parser.parse_args()

    samples = args.samples or get_test_samples(args.n)
    print(f"Will annotate {len(samples)} samples")

    root = tk.Tk()
    App(root, samples, scale=args.scale, resume=args.resume, force=args.force)
    root.mainloop()


if __name__ == "__main__":
    main()
