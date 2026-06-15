"""
手动标注 target 字符裁剪/分割点工具 — 针对 click1 (1个目标字符)。
使用 4 条线 (2 竖 + 2 横) 框选出唯一的目标字符。

用法:
  python manual_plan_split_click1.py --force
  python manual_plan_split_click1.py --resume --scale 5

操作:
  - A/D 左右/上下移动当前线 (竖线左右, 横线上下)
  - Tab 切换选中的线 (S1→S2→S3→S4)
  - S/Enter 保存并下一张
  - ← → 翻页
  - Q 退出

线序:
  S1(红)=左边界  S2(绿)=右边界  S3(蓝)=上边界  S4(黄)=下边界
"""

import argparse
import json
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from PIL import Image, ImageTk

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "dataset" / "click1"
SAVE_PATH = PROJECT_ROOT / "dataset" / "manual_splits_click1.json"

# 4 条线颜色
POINT_COLORS = {1: "#ff4d6d", 2: "#00d084", 3: "#4da6ff", 4: "#ffb000"}


def get_test_samples(n: int = 100) -> list[str]:
    valid = []
    if DATA_DIR.exists():
        for d in sorted(os.listdir(DATA_DIR)):
            if d.startswith("sample_"):
                if (DATA_DIR / d / f"{d}_target.png").exists():
                    valid.append(d)
    return valid[:n]


def load_splits() -> dict:
    if SAVE_PATH.exists():
        return json.loads(SAVE_PATH.read_text(encoding="utf-8"))
    return {}


def save_splits(splits: dict) -> None:
    SAVE_PATH.write_text(json.dumps(splits, ensure_ascii=False, indent=2), encoding="utf-8")


class App:
    def __init__(self, root: tk.Tk, samples: list[str], scale: float, resume: bool, force: bool = False):
        self.root = root
        self.samples = samples
        self.scale = scale
        self.idx = 0
        self.selected = 0  # 0-3 → S1-S4
        # 初始默认坐标: x1=5, x2=25, y1=5, y2=27
        self.points = [5, 25, 5, 27]
        self.last_points = [5, 25, 5, 27]
        self.dirty = False
        self.splits = {} if force else load_splits()

        if resume:
            for i, s in enumerate(samples):
                if s not in self.splits:
                    self.idx = i
                    break

        self.root.title("Click1 Target Crop Annotator")
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
        
        # 只预览1个目标
        lbl = tk.Label(self.preview_frame, text="P1", bg="#1e1e1e", fg="#cccccc",
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
        if not self.samples:
            messagebox.showinfo("完成", "没有找到样本数据！")
            self.root.destroy()
            return
            
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

        # 加载历史记录，如果该图没标注过，继承上一张保存的最后坐标
        if name in self.splits:
            s = self.splits[name]
            self.points = [s["x1"], s["x2"], s["y1"], s["y2"]]
            self.last_points = self.points.copy()
        else:
            self.points = self.last_points.copy()
            
        self.dirty = False
        self.selected = 0
        self.redraw()

    def redraw(self):
        self.canvas.delete("all")
        name = self.samples[self.idx]
        w, h = self.img.size
        sw, sh = int(w * self.scale), int(h * self.scale)

        self.canvas.create_image(0, 0, image=self._display_photo, anchor="nw")

        # Manual lines: S1-S2 竖线, S3-S4 横线
        for i in range(4):
            color = POINT_COLORS.get(i + 1, "#ffffff")
            is_selected = (i == self.selected)
            width = 3 if is_selected else 2
            val = self.points[i]

            if i < 2:  # 竖线
                sx = val * self.scale
                self.canvas.create_line(sx, 0, sx, sh, fill=color, width=width)
                label = f"S{i+1}={val}" + (" ◄" if is_selected else "")
                self.canvas.create_text(sx + 5, 5 + i * 18, text=label, fill=color,
                                        font=("Consolas", 10, "bold" if is_selected else "normal"), anchor="nw")
            else:  # 横线
                sy = val * self.scale
                self.canvas.create_line(0, sy, sw, sy, fill=color, width=width)
                label = f"S{i+1}={val}" + (" ◄" if is_selected else "")
                self.canvas.create_text(5, sy + 3 + (i - 2) * 16, text=label, fill=color,
                                        font=("Consolas", 10, "bold" if is_selected else "normal"), anchor="nw")

        # Shade region between S1-S2, clipped to S3-S4
        x1, x2, y1, y2 = self.points
        if x1 < x2 and y1 < y2:
            sx1, sx2 = int(x1 * self.scale), int(x2 * self.scale)
            sy1, sy2 = int(y1 * self.scale), int(y2 * self.scale)
            color = "#00d084"
            self.canvas.create_rectangle(sx1, sy1, sx2, sy2, outline=color, width=2, dash=(4, 4))
            self.canvas.create_text((sx1 + sx2) // 2, (sy1 + sy2) // 2, text="TARGET",
                                    fill=color, font=("Consolas", 14, "bold"))

        # Header
        labeled = sum(1 for s in self.samples if s in self.splits)
        self.header.config(text=f"{name}  ({self.idx+1}/{len(self.samples)})  "
                                f"已标注 {labeled}/{len(self.samples)}  "
                                f"x=[{x1},{x2}] y=[{y1},{y2}]")
        self.footer.config(text="A/D移动 | Tab切换(S1→S2→S3→S4) | S/Enter保存 | ←→翻页 | Q退出")

        self._update_previews()

    def _update_previews(self):
        self._photos.clear()
        w, h = self.img.size
        x1, x2, y1, y2 = self.points
        if x1 < x2 and y1 < y2:
            crop = self.img.crop((x1, y1, x2, y2))
            disp = crop.resize((80, 80), Image.Resampling.NEAREST)
            photo = ImageTk.PhotoImage(disp)
            self._photos.append(photo)
            self.preview_labels[0].config(image=photo, text=f"Target [{x1}:{x2}, {y1}:{y2}]")
        else:
            self.preview_labels[0].config(image="", text="Invalid Box")

    def move(self, delta):
        i = self.selected
        if i < 2:
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
        self.selected = (self.selected + 1) % 4
        self.redraw()

    def _save(self) -> bool:
        x1, x2, y1, y2 = self.points
        if not (x1 < x2):
            messagebox.showwarning("错误", "S1 < S2 (竖线) 必须严格递增")
            return False
        if not (y1 < y2):
            messagebox.showwarning("错误", "S3 < S4 (横线) 必须严格递增")
            return False
        self.splits[self.samples[self.idx]] = {
            "x1": x1, "x2": x2, "y1": y1, "y2": y2
        }
        self.last_points = self.points.copy()
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
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--scale", type=float, default=6.0)
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
