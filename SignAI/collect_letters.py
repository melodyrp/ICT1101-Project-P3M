"""Collect your own ASL A-Z landmark samples from the webcam.

Usage examples:
    python .\SignAI\collect_letters.py --session 1 --target 60
    python .\SignAI\collect_letters.py --session 2 --target 60
    python .\SignAI\collect_letters.py --session 3 --target 60

Controls in the webcam window:
    A-Z   : select the letter you want to record
    SPACE : start/stop recording for the selected letter
    ESC   : quit and save

The script stores only normalized MediaPipe hand-landmark numbers, not photos.
"""
from __future__ import annotations

import argparse
import csv
import time
from collections import Counter
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from fingerspell_team import (
    draw_hand,
    fallback_normalize,
    find_external_repo,
    find_hand_model,
    load_config,
)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DATA_PATH = DATA_DIR / "personal_letters.csv"
FEATURE_NAMES = [f"f{i}" for i in range(63)]


def load_counts(session: str) -> Counter:
    counts = Counter()
    if not DATA_PATH.exists():
        return counts
    with DATA_PATH.open("r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("session") == session:
                counts[row["label"].upper()] += 1
    return counts


def ensure_header() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_PATH.exists():
        with DATA_PATH.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["label", "session", "timestamp", *FEATURE_NAMES])


def append_sample(label: str, session: str, features: np.ndarray) -> None:
    with DATA_PATH.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            label,
            session,
            f"{time.time():.6f}",
            *[f"{float(v):.8f}" for v in features],
        ])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="1", help="Collection session ID, e.g. 1, 2, 3")
    parser.add_argument("--target", type=int, default=60, help="Samples per letter in this session")
    parser.add_argument("--every", type=int, default=3, help="Record one sample every N detected frames")
    args = parser.parse_args()

    ensure_header()
    counts = load_counts(str(args.session))

    cfg = load_config()
    repo = find_external_repo(cfg)
    hand_model_path = find_hand_model(cfg, repo)

    BaseOptions = mp.tasks.BaseOptions
    HandLandmarker = mp.tasks.vision.HandLandmarker
    HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
    RunningMode = mp.tasks.vision.RunningMode

    options = HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(hand_model_path)),
        running_mode=RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    cap = cv2.VideoCapture(int(cfg.get("camera_index", 0)))
    if not cap.isOpened():
        raise RuntimeError("Could not open webcam.")

    selected = "A"
    recording = False
    detected_frame_count = 0
    started = time.monotonic()

    print(f"[Collect] Saving to: {DATA_PATH}")
    print(f"[Collect] Session: {args.session} | target per letter: {args.target}")
    print("[Collect] A-Z select letter | SPACE record/pause | ESC quit")
    print("[Collect] Move/rotate your hand slightly while recording; do not keep one frozen pose.")

    with HandLandmarker.create_from_options(options) as landmarker:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            timestamp_ms = int((time.monotonic() - started) * 1000)
            result = landmarker.detect_for_video(mp_image, timestamp_ms)

            hand_found = bool(result.hand_landmarks)
            if hand_found:
                hand = result.hand_landmarks[0]
                draw_hand(frame, hand)
                points = np.array([[lm.x, lm.y, lm.z] for lm in hand], dtype=np.float32)
                features = fallback_normalize(points)

                if recording and counts[selected] < args.target:
                    detected_frame_count += 1
                    if detected_frame_count % max(1, args.every) == 0:
                        append_sample(selected, str(args.session), features)
                        counts[selected] += 1
                        if counts[selected] >= args.target:
                            recording = False
                            print(f"[Collect] {selected}: complete ({counts[selected]}/{args.target})")
            else:
                detected_frame_count = 0

            status = "RECORDING" if recording else "PAUSED"
            cv2.rectangle(frame, (0, 0), (frame.shape[1], 130), (20, 20, 20), -1)
            cv2.putText(frame, f"PERSONAL DATA | Session {args.session}", (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.66, (255,255,255), 2)
            cv2.putText(frame, f"Letter: {selected}   {counts[selected]}/{args.target}   {status}", (15, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (0,255,0) if recording else (255,255,255), 2)
            cv2.putText(frame, "A-Z select | SPACE record/pause | ESC quit", (15, 92), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255,255,255), 1)
            cv2.putText(frame, "Vary angle/distance slightly while recording", (15, 118), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255,255,255), 1)

            cv2.imshow("Collect Personal ASL Letters", frame)
            key = cv2.waitKey(1) & 0xFF

            if key == 27:  # ESC = quit
                break
            elif key == 32:  # SPACE = record/pause
                if counts[selected] >= args.target:
                    print(f"[Collect] {selected} already has {counts[selected]} samples for session {args.session}.")
                    recording = False
                else:
                    recording = not recording
                    detected_frame_count = 0
                    print(f"[Collect] {selected}: {'RECORDING' if recording else 'PAUSED'}")
            elif ord("a") <= key <= ord("z"):
                selected = chr(key).upper()
                recording = False
                detected_frame_count = 0
                print(f"[Collect] Selected {selected}: {counts[selected]}/{args.target}")

    cap.release()
    cv2.destroyAllWindows()

    print("\n[Collect] Session totals:")
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        print(f"  {letter}: {counts[letter]}")
    print(f"[Collect] Saved: {DATA_PATH}")
    print("[Collect] J and Z use motion in real ASL, so a static-frame model will remain weaker on them.")


if __name__ == "__main__":
    main()
