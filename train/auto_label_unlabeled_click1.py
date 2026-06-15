from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from core.captcha_text_select_v2 import get_click_solver_v2


SAMPLE_RE = re.compile(r"^sample_(\d{5})$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-label unlabeled click1 samples with CaptchaTextSelectSolverV2 and create review visualizations."
    )
    parser.add_argument("--dataset", type=Path, default=Path("dataset/click1"))
    parser.add_argument("--output-dir", type=Path, default=Path("runs/click1_auto_label/text_select_v2"))
    parser.add_argument("--start", type=int, default=None, help="First sample number to process, for example 1001.")
    parser.add_argument("--end", type=int, default=None, help="Last sample number to process, inclusive.")
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--samples-file", type=Path, default=None, help="Optional list of sample names to process.")
    parser.add_argument("--include-labeled", action="store_true", help="Also process samples that already have label.json.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing auto-label output files.")
    parser.add_argument(
        "--write-dataset-labels",
        action="store_true",
        help="Write label.json into sample folders. Default is review-only and does not modify sample labels.",
    )
    parser.add_argument("--page-size", type=int, default=25, help="Images per contact-sheet review page. 0 disables pages.")
    return parser.parse_args()


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


def load_sample_list(path: Path) -> set[str]:
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.add(line.split(",", 1)[0].strip())
    return names


def find_samples(
    dataset: Path,
    include_labeled: bool,
    samples_file: Path | None,
    start: int | None,
    end: int | None,
) -> list[Path]:
    wanted = load_sample_list(samples_file) if samples_file is not None else None
    samples = []
    for sample_dir in sorted(dataset.glob("sample_*")):
        if not sample_dir.is_dir():
            continue
        match = SAMPLE_RE.match(sample_dir.name)
        if not match:
            continue
        sample_index = int(match.group(1))
        if start is not None and sample_index < start:
            continue
        if end is not None and sample_index > end:
            continue
        if wanted is not None and sample_dir.name not in wanted:
            continue
        if not include_labeled and (sample_dir / "label.json").exists():
            continue
        target_path = sample_dir / f"{sample_dir.name}_target.png"
        bg_path = sample_dir / f"{sample_dir.name}_bg.png"
        if target_path.exists() and bg_path.exists():
            samples.append(sample_dir)
    return samples


def clean_label_payload(sample_name: str) -> dict[str, object]:
    return {
        "sample": sample_name,
        "target_count": 0,
        "points": [],
        "bg": f"{sample_name}_bg.png",
        "target": f"{sample_name}_target.png",
    }


def make_label(sample_name: str, points: list[tuple[int, int]]) -> dict[str, object]:
    payload = clean_label_payload(sample_name)
    payload["target_count"] = len(points)
    payload["points"] = [{"x": int(x), "y": int(y)} for x, y in points]
    return payload


def draw_review(
    target_bytes: bytes,
    bg_bytes: bytes,
    sample_name: str,
    points: list[tuple[int, int]],
    output_path: Path,
) -> None:
    target = Image.open(BytesIO(target_bytes)).convert("RGB")
    bg = Image.open(BytesIO(bg_bytes)).convert("RGB")
    target_scale = 4
    target_big = target.resize((target.width * target_scale, target.height * target_scale), Image.Resampling.NEAREST)
    font = load_font(14)

    width = max(bg.width, target_big.width, 560)
    header_h = 34
    target_h = target_big.height + 20
    gap = 12
    height = header_h + target_h + gap + bg.height + 12
    canvas = Image.new("RGB", (width, height), (245, 246, 248))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, width, header_h], fill=(25, 31, 38))
    draw.text((10, 8), sample_name, fill=(255, 255, 255), font=font)

    target_x = 10
    target_y = header_h + 10
    canvas.paste(target_big, (target_x, target_y))

    bg_x = 0
    bg_y = header_h + target_h + gap
    canvas.paste(bg, (bg_x, bg_y))

    if not points:
        draw.rectangle([0, bg_y, width, bg_y + 24], fill=(120, 0, 0))
        draw.text((8, bg_y + 4), "NO PREDICTION", fill=(255, 255, 255), font=font)
    else:
        for index, (x, y) in enumerate(points, start=1):
            color = (0, 210, 120)
            draw.ellipse([x - 8, bg_y + y - 8, x + 8, bg_y + y + 8], outline=color, width=3)
            draw.text((x + 10, bg_y + y - 8), f"P{index}", fill=color, font=font)
            if index > 1:
                px, py = points[index - 2]
                draw.line([px, bg_y + py, x, bg_y + y], fill=color, width=1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=92)


def make_contact_sheets(vis_paths: list[Path], pages_dir: Path, page_size: int) -> list[Path]:
    if page_size <= 0:
        return []
    pages_dir.mkdir(parents=True, exist_ok=True)
    page_paths: list[Path] = []
    cols = 5
    thumb_w, thumb_h = 320, 250
    rows = max(1, (page_size + cols - 1) // cols)
    font = load_font(12)
    for page_index, start in enumerate(range(0, len(vis_paths), page_size), start=1):
        chunk = vis_paths[start : start + page_size]
        page = Image.new("RGB", (cols * thumb_w, rows * thumb_h), (230, 232, 236))
        draw = ImageDraw.Draw(page)
        for item_index, path in enumerate(chunk):
            image = Image.open(path).convert("RGB")
            image = ImageOps.contain(image, (thumb_w, thumb_h - 22))
            x = (item_index % cols) * thumb_w
            y = (item_index // cols) * thumb_h
            page.paste(image, (x, y + 20))
            draw.rectangle([x, y, x + thumb_w - 1, y + thumb_h - 1], outline=(180, 184, 190))
            draw.text((x + 5, y + 3), path.stem, fill=(20, 24, 28), font=font)
        page_path = pages_dir / f"review_page_{page_index:04d}.jpg"
        page.save(page_path, quality=90)
        page_paths.append(page_path)
    return page_paths


def write_review_html(output_dir: Path, rows: list[dict[str, object]]) -> Path:
    html_path = output_dir / "review.html"
    cards = []
    for row in rows:
        sample = html.escape(str(row["sample"]))
        status = html.escape(str(row["status"]))
        vis = html.escape(str(Path(str(row["vis_path"])).relative_to(output_dir)).replace("\\", "/"))
        points = html.escape(str(row.get("points", "")))
        cards.append(
            f'<article class="card status-{status}">'
            f'<h2>{sample} <span>{status}</span></h2>'
            f'<a href="{vis}" target="_blank"><img src="{vis}" loading="lazy"></a>'
            f'<p>points: {points}</p>'
            f"</article>"
        )
    html_text = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>click1 auto-label review</title>
<style>
body{margin:0;font:14px/1.4 Arial,"Microsoft YaHei",sans-serif;background:#f4f5f7;color:#15181d}
header{position:sticky;top:0;background:#1c232b;color:white;padding:12px 18px;z-index:1}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px;padding:12px}
.card{background:white;border:1px solid #d7dbe0;border-radius:6px;overflow:hidden}
.card h2{font-size:14px;margin:0;padding:8px 10px;display:flex;justify-content:space-between;background:#edf1f5}
.card img{width:100%;display:block}
.card p{margin:6px 10px;color:#44505c;word-break:break-all}
.status-ok h2{background:#dff5ea}
.status-need_rerun h2,.status-no_prediction h2{background:#ffe4df}
</style>
</head>
<body>
<header>click1 auto-label review</header>
<main class="grid">
""" + "\n".join(cards) + """
</main>
</body>
</html>
"""
    html_path.write_text(html_text, encoding="utf-8")
    return html_path


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    labels_dir = output_dir / "labels"
    details_dir = output_dir / "details"
    vis_dir = output_dir / "vis"
    labels_dir.mkdir(parents=True, exist_ok=True)
    details_dir.mkdir(parents=True, exist_ok=True)
    vis_dir.mkdir(parents=True, exist_ok=True)

    samples = find_samples(args.dataset, args.include_labeled, args.samples_file, args.start, args.end)
    if args.max_samples > 0:
        samples = samples[: args.max_samples]
    if not samples:
        raise SystemExit("No samples to process.")

    solver = get_click_solver_v2()

    rows: list[dict[str, object]] = []
    vis_paths: list[Path] = []
    start_time = time.time()
    for index, sample_dir in enumerate(samples, start=1):
        sample_name = sample_dir.name
        label_path = labels_dir / f"{sample_name}.json"
        detail_path = details_dir / f"{sample_name}.json"
        vis_path = vis_dir / f"{sample_name}.jpg"
        if detail_path.exists() and label_path.exists() and vis_path.exists() and not args.overwrite:
            continue

        target_path = sample_dir / f"{sample_name}_target.png"
        bg_path = sample_dir / f"{sample_name}_bg.png"
        target_bytes = target_path.read_bytes()
        bg_bytes = bg_path.read_bytes()

        points = solver.solve(target_bytes, bg_bytes)
        
        status = "ok" if points and len(points) > 0 else "no_prediction"

        draw_review(target_bytes, bg_bytes, sample_name, points, vis_path)
        vis_paths.append(vis_path)

        label_payload = make_label(sample_name, points)
        if status == "ok":
            label_path.write_text(json.dumps(label_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            if args.write_dataset_labels:
                dataset_label_path = sample_dir / "label.json"
                if args.overwrite or not dataset_label_path.exists():
                    dataset_label_path.write_text(
                        json.dumps(label_payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
        else:
            label_path.write_text(json.dumps(clean_label_payload(sample_name), ensure_ascii=False, indent=2), encoding="utf-8")

        detail_payload = {
            "sample": sample_name,
            "status": status,
            "points": points,
            "target": str(target_path.resolve()),
            "bg": str(bg_path.resolve()),
            "label_candidate": str(label_path.resolve()),
            "vis": str(vis_path.resolve()),
        }
        detail_path.write_text(json.dumps(detail_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        row = {
            "sample": sample_name,
            "status": status,
            "points": json.dumps(points, ensure_ascii=False),
            "label_path": str(label_path),
            "detail_path": str(detail_path),
            "vis_path": str(vis_path),
        }
        rows.append(row)

        if index == 1 or index % 25 == 0 or index == len(samples):
            elapsed = time.time() - start_time
            print(f"[{index}/{len(samples)}] {sample_name} status={status} elapsed={elapsed:.1f}s")

    manifest_path = output_dir / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as fh:
        fieldnames = [
            "sample",
            "status",
            "points",
            "label_path",
            "detail_path",
            "vis_path",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    page_paths = make_contact_sheets(vis_paths, output_dir / "review_pages", args.page_size)
    html_path = write_review_html(output_dir, rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
    summary = {
        "processed": len(rows),
        "status_counts": counts,
        "manifest": str(manifest_path),
        "review_html": str(html_path),
        "review_pages": len(page_paths),
        "labels_dir": str(labels_dir),
        "details_dir": str(details_dir),
        "vis_dir": str(vis_dir),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
