from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply reviewed click3 auto-labels into dataset sample folders.")
    parser.add_argument("--dataset", type=Path, default=Path("dataset/click3"))
    parser.add_argument("--auto-label-dir", type=Path, default=Path("runs/click3_auto_label/yolo4_siamese_posw3"))
    parser.add_argument("--samples-file", type=Path, default=None, help="Optional accepted sample names, one per line.")
    parser.add_argument("--status", default="ok", help='Manifest status to apply. Use "all" to ignore status.')
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing dataset label.json files.")
    return parser.parse_args()


def load_names(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.add(line.split(",", 1)[0].strip())
    return names


def main() -> None:
    args = parse_args()
    manifest_path = args.auto_label_dir / "manifest.csv"
    labels_dir = args.auto_label_dir / "labels"
    if not manifest_path.exists():
        raise SystemExit(f"manifest not found: {manifest_path}")
    if not labels_dir.exists():
        raise SystemExit(f"labels dir not found: {labels_dir}")

    accepted_names = load_names(args.samples_file)
    applied = 0
    skipped = 0
    missing = 0
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            sample = row["sample"]
            if accepted_names is not None and sample not in accepted_names:
                skipped += 1
                continue
            if args.status != "all" and row.get("status") != args.status:
                skipped += 1
                continue
            source = labels_dir / f"{sample}.json"
            target = args.dataset / sample / "label.json"
            if not source.exists() or not target.parent.exists():
                missing += 1
                continue
            if target.exists() and not args.overwrite:
                skipped += 1
                continue
            payload = json.loads(source.read_text(encoding="utf-8"))
            if len(payload.get("points", [])) != 3:
                skipped += 1
                continue
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            applied += 1

    print(
        json.dumps(
            {
                "applied": applied,
                "skipped": skipped,
                "missing": missing,
                "dataset": str(args.dataset.resolve()),
                "auto_label_dir": str(args.auto_label_dir.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
