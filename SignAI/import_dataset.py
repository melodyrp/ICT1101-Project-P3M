r"""Import a public ASL alphabet image dataset as hand-landmark training data.

The dataset folder must contain one subfolder per letter, e.g.

    asl_kaggle_data\
        a\  img1.jpg  img2.jpg ...
        b\  ...
        nothing\  (optional - becomes the NOTHING class)

For every image, MediaPipe finds the hand, the 21 landmarks are normalized with
the SAME fallback_normalize() used by collect_letters.py / fingerspell_team.py,
and one row is appended to SignAI\data\personal_letters.csv. Images are never
copied - keep the dataset OUTSIDE the team repo.

Usage (from the team repo root, .venv active):
    python .\SignAI\import_dataset.py "C:\path\to\asl_kaggle_data" --session kaggle --per-class 300

Then train:
    python .\SignAI\train_letters.py --val-session <your own session>   (honest test)
    python .\SignAI\train_letters.py --final                            (demo model)

Remember to credit the dataset in the video and README.
"""
from __future__ import annotations

import argparse
import random
from collections import Counter
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from collect_letters import append_sample, ensure_header, load_counts, DATA_PATH
from fingerspell_team import fallback_normalize, find_external_repo, find_hand_model, load_config

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
LETTERS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
NOTHING_NAMES = {"NOTHING", "NONE", "BLANK", "NOTHING_CLASS"}


def folder_to_label(name: str) -> str | None:
    """Map a dataset folder name to our label, or None to skip it."""
    up = name.strip().upper()
    if up in LETTERS:
        return up
    if up in NOTHING_NAMES:
        return "NOTHING"
    return None   # digits, 'del', 'space', etc. are skipped


def read_image(path: Path):
    # np.fromfile + imdecode works with any Windows path (cv2.imread can fail on some)
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def prepare(img: np.ndarray) -> np.ndarray:
    """Upscale small images and add a border - MediaPipe struggles with tight crops."""
    h, w = img.shape[:2]
    if min(h, w) < 400:
        f = 400 / min(h, w)
        img = cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_LINEAR)
    pad = int(0.25 * max(img.shape[:2]))
    return cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_REPLICATE)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path, help="Folder with one subfolder per letter")
    parser.add_argument("--session", default="kaggle", help="Session name stored with these rows")
    parser.add_argument("--per-class", type=int, default=300, help="Max images to use per letter")
    parser.add_argument("--mirror", action="store_true",
                        help="Flip images horizontally first (try if the dataset uses the other hand)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not args.dataset.is_dir():
        raise FileNotFoundError(f"Dataset folder not found: {args.dataset}")

    # Find class folders (also handles one extra nesting level, e.g. dataset\train\a\...)
    class_dirs = [d for d in args.dataset.iterdir() if d.is_dir() and folder_to_label(d.name)]
    if not class_dirs:
        for sub in args.dataset.iterdir():
            if sub.is_dir():
                inner = [d for d in sub.iterdir() if d.is_dir() and folder_to_label(d.name)]
                if inner:
                    print(f"[Import] Using class folders inside: {sub}")
                    class_dirs = inner
                    break
    if not class_dirs:
        raise RuntimeError("No letter folders (a, b, c ...) found in the dataset folder.")

    ensure_header()
    existing = load_counts(args.session)
    if sum(existing.values()):
        print(f"[Import] Session '{args.session}' already has {sum(existing.values())} rows - "
              "new rows are added up to --per-class per letter.")

    cfg = load_config()
    hand_model = find_hand_model(cfg, find_external_repo(cfg))
    options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(hand_model)),
        running_mode=mp.tasks.vision.RunningMode.IMAGE,
        num_hands=1,
        min_hand_detection_confidence=0.5,
    )

    rng = random.Random(args.seed)
    added, skipped = Counter(), Counter()

    with mp.tasks.vision.HandLandmarker.create_from_options(options) as landmarker:
        for d in sorted(class_dirs, key=lambda p: p.name.upper()):
            label = folder_to_label(d.name)
            need = args.per_class - existing[label]
            if need <= 0:
                print(f"[Import] {label}: already has {existing[label]}, skipping")
                continue

            files = [f for f in d.rglob("*") if f.suffix.lower() in IMAGE_EXTS]
            rng.shuffle(files)

            for f in files:
                if added[label] >= need:
                    break
                img = read_image(f)
                if img is None:
                    skipped[label] += 1
                    continue
                if args.mirror:
                    img = cv2.flip(img, 1)
                rgb = cv2.cvtColor(prepare(img), cv2.COLOR_BGR2RGB)
                result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))

                # Images without a detectable hand are skipped (this includes most
                # 'nothing' images - record your own NOTHING class with collect_letters.py).
                if not result.hand_landmarks:
                    skipped[label] += 1
                    continue

                hand = result.hand_landmarks[0]
                points = np.array([[lm.x, lm.y, lm.z] for lm in hand], dtype=np.float32)
                append_sample(label, args.session, fallback_normalize(points))
                added[label] += 1

            total_tried = added[label] + skipped[label]
            print(f"[Import] {label}: added {added[label]}  (no hand found in {skipped[label]} of {total_tried})")

    print(f"\n[Import] Done. Added {sum(added.values())} rows to {DATA_PATH}")
    low = [l for l in sorted(LETTERS) if existing[l] + added[l] < 50]
    if low:
        print("[Import] Few samples for: " + ", ".join(low) +
              "  (record these yourself with collect_letters.py)")
    print("[Import] Next: python .\\SignAI\\train_letters.py --val-session <your session>")


if __name__ == "__main__":
    main()
