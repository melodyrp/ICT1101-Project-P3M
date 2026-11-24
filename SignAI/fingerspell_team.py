"""Person 1 ASL fingerspelling mode.

Uses the pretrained model files from:
https://github.com/ronronrivera/real-time-asl-detection

The external repository stays OUTSIDE the team Git repository. This script
loads its pretrained PyTorch weights + label encoder and uses MediaPipe
HandLandmarker for webcam inference.

Every registered letter is sent straight to Backend/main.py (TCP 5560), so it
shows live on Unit A. The text lives in the backend: Unit A's buttons and the
keys below edit the same text, and this window shows what Unit A shows.

Controls (same as Unit A's buttons)
--------
SPACE      add a space between words
BACKSPACE  delete the last letter (= UNDO)
C          clear everything
ENTER      speak the text on Unit B (= SEND)
Q / ESC    quit

Important: J and Z are motion-based ASL letters; a static-frame alphabet model
is inherently weaker on those letters.
"""
from __future__ import annotations

import importlib.util
import json
import pickle
import sys
import time
from collections import deque
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
import torch
import torch.nn as nn

from fingerspell_bridge import send_key, send_letter

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "fingerspelling_config.json"


def load_config() -> dict:
    cfg = {
        "camera_index": 0,
        "confidence_threshold": 0.80,
        "stable_frames": 12,
        "release_frames": 6,
        "window_name": "Person 1 - ASL Fingerspelling",
        "external_repo_relative": "..\\..\\asl_fingerspell_model",
        "hand_model_candidates": [
            "..\\..\\sign_lang_trans\\hand_landmarker.task",
            "hand_landmarker.task",
        ],
    }
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig")))
    return cfg


def find_external_repo(cfg: dict) -> Path:
    candidates = [
        (HERE / str(cfg.get("external_repo_relative", ""))).resolve(),
        (HERE.parent.parent / "asl_fingerspell_model").resolve(),
        (HERE.parent.parent / "real-time-asl-detection").resolve(),
    ]
    for p in candidates:
        if (p / "models" / "asl_landmark_mlp.pth").exists() and (p / "landmark_label_encoder.pkl").exists():
            return p
    raise FileNotFoundError(
        "Could not find the pretrained fingerspelling repo.\n"
        "Run SignAI\\install_fingerspelling.ps1 first."
    )


def find_hand_model(cfg: dict, external_repo: Path) -> Path:
    candidates = []
    for raw in cfg.get("hand_model_candidates", []):
        candidates.append((HERE / raw).resolve())
    candidates.extend([
        external_repo / "hand_landmarker.task",
        HERE.parent.parent / "sign_lang_trans" / "hand_landmarker.task",
    ])
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "No MediaPipe hand_landmarker.task found. Keep sign_lang_trans beside "
        "the team repo, or download the official MediaPipe HandLandmarker task."
    )


def load_label_encoder(path: Path):
    try:
        import joblib
        return joblib.load(path)
    except Exception:
        with path.open("rb") as fh:
            return pickle.load(fh)


class DynamicMLP(nn.Module):
    """Rebuild a simple Linear/ReLU MLP directly from checkpoint tensors.

    The upstream model is documented as 63 -> 128 -> 64 -> 36. Reconstructing
    from the stored matrix shapes also makes this tolerant of harmless naming
    changes in the external repository.
    """
    def __init__(self, layer_shapes: list[tuple[int, int]]):
        super().__init__()
        layers = []
        for idx, (out_features, in_features) in enumerate(layer_shapes):
            layers.append(nn.Linear(in_features, out_features))
            if idx != len(layer_shapes) - 1:
                layers.append(nn.ReLU())
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)


def _state_dict_from_checkpoint(checkpoint):
    if isinstance(checkpoint, nn.Module):
        return checkpoint
    if isinstance(checkpoint, dict):
        for key in ("state_dict", "model_state_dict", "model"):
            if key in checkpoint and isinstance(checkpoint[key], dict):
                return checkpoint[key]
        if any(torch.is_tensor(v) for v in checkpoint.values()):
            return checkpoint
    raise RuntimeError("Unsupported fingerspelling checkpoint format.")


def load_model(model_path: Path):
    checkpoint = torch.load(model_path, map_location="cpu")
    if isinstance(checkpoint, nn.Module):
        checkpoint.eval()
        return checkpoint

    state = _state_dict_from_checkpoint(checkpoint)
    weight_items = [(k, v) for k, v in state.items() if torch.is_tensor(v) and v.ndim == 2]
    if not weight_items:
        raise RuntimeError("No Linear layer weights found in checkpoint.")

    # State dict order follows module registration order for standard PyTorch models.
    layer_shapes = [(int(v.shape[0]), int(v.shape[1])) for _, v in weight_items]
    model = DynamicMLP(layer_shapes)

    linear_layers = [m for m in model.modules() if isinstance(m, nn.Linear)]
    bias_map = {k.rsplit(".weight", 1)[0] + ".bias": v for k, v in weight_items}

    for linear, (weight_key, weight_tensor) in zip(linear_layers, weight_items):
        linear.weight.data.copy_(weight_tensor.float())
        bias_key = weight_key.rsplit(".weight", 1)[0] + ".bias"
        bias_tensor = state.get(bias_key)
        if torch.is_tensor(bias_tensor) and bias_tensor.numel() == linear.out_features:
            linear.bias.data.copy_(bias_tensor.float())
        else:
            linear.bias.data.zero_()

    model.eval()
    return model


def import_external_normalizer(external_repo: Path):
    path = external_repo / "src" / "landmark_utils.py"
    if not path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("external_landmark_utils", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        funcs = []
        for name in dir(module):
            value = getattr(module, name)
            if callable(value) and "norm" in name.lower():
                funcs.append(value)
        return funcs
    except Exception as exc:
        print(f"[Fingerspell] Could not import upstream normalizer: {exc}")
        return None


def fallback_normalize(points: np.ndarray) -> np.ndarray:
    """Wrist-centred + hand-size normalization."""
    pts = points.astype(np.float32).copy()
    pts -= pts[0]
    # Use the furthest landmark distance as a stable hand-size estimate.
    scale = float(np.max(np.linalg.norm(pts, axis=1)))
    if scale > 1e-6:
        pts /= scale
    return pts.reshape(-1)


def upstream_normalize(points: np.ndarray) -> np.ndarray:
    """Normalization used to TRAIN the pretrained upstream model
    (ronronrivera/real-time-asl-detection, src/landmark_utils.py):
    wrist at origin, scaled by the wrist -> middle-finger MCP (point 9) distance.
    Use this for the pretrained model only. The personal model and
    collect_letters.py use fallback_normalize() above."""
    pts = points.astype(np.float32).copy()
    pts -= pts[0]
    scale = float(np.linalg.norm(pts[9]))
    if scale > 1e-6:
        pts /= scale
    return pts.reshape(-1)


def normalize_points(points: np.ndarray, normalizers) -> np.ndarray:
    if normalizers:
        test_inputs = [points, points.tolist(), points.reshape(-1)]
        for func in normalizers:
            for value in test_inputs:
                try:
                    out = func(value)
                    arr = np.asarray(out, dtype=np.float32).reshape(-1)
                    if arr.size == 63 and np.all(np.isfinite(arr)):
                        return arr
                except Exception:
                    pass
    return upstream_normalize(points)


def decode_label(encoder, index: int) -> str:
    if hasattr(encoder, "inverse_transform"):
        value = encoder.inverse_transform([index])[0]
        return str(value).upper()
    if hasattr(encoder, "classes_"):
        classes = list(encoder.classes_)
        return str(classes[index]).upper()
    if isinstance(encoder, (list, tuple, np.ndarray)):
        return str(encoder[index]).upper()
    return str(index)


def draw_hand(frame, landmarks):
    h, w = frame.shape[:2]
    for lm in landmarks:
        x, y = int(lm.x * w), int(lm.y * h)
        cv2.circle(frame, (x, y), 4, (0, 255, 0), -1)


def main():
    cfg = load_config()
    repo = find_external_repo(cfg)
    hand_model_path = find_hand_model(cfg, repo)

    personal_model = HERE / "models" / "my_fingerspell_model.pth"
    personal_encoder = HERE / "models" / "my_fingerspell_label_encoder.pkl"
    using_personal = personal_model.exists() and personal_encoder.exists()

    if using_personal:
        model = load_model(personal_model)
        encoder = load_label_encoder(personal_encoder)
        normalizers = None
        print(f"[Fingerspell] Using PERSONAL model: {personal_model}")
    else:
        model = load_model(repo / "models" / "asl_landmark_mlp.pth")
        encoder = load_label_encoder(repo / "landmark_label_encoder.pkl")
        normalizers = import_external_normalizer(repo)
        print(f"[Fingerspell] Using pretrained model from: {repo}")

    # Ignore digit classes (0 looks like O, 2 like V ...). Other classes such as
    # NOTHING (relaxed hand / transitions) stay, but are never typed.
    labels = [decode_label(encoder, i) for i in range(len(encoder.classes_))]
    letter_mask = torch.tensor([not l.isdigit() for l in labels])

    print(f"[Fingerspell] Model repo: {repo}")
    print(f"[Fingerspell] Hand model: {hand_model_path}")
    print("[Fingerspell] Controls: SPACE word | BACKSPACE delete | C clear | ENTER send | Q quit")

    BaseOptions = mp.tasks.BaseOptions
    HandLandmarker = mp.tasks.vision.HandLandmarker
    HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
    RunningMode = mp.tasks.vision.RunningMode

    options = HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(hand_model_path)),
        running_mode=RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.7,
        min_hand_presence_confidence=0.7,
        min_tracking_confidence=0.7,
    )

    cap = cv2.VideoCapture(int(cfg.get("camera_index", 0)))
    if not cap.isOpened():
        raise RuntimeError("Could not open webcam.")

    threshold = float(cfg.get("confidence_threshold", 0.80))
    stable_needed = int(cfg.get("stable_frames", 12))
    release_needed = int(cfg.get("release_frames", 6))

    spelled = ""          # the text as the backend / Unit A has it
    online = False
    next_sync = 0.0
    candidate = ""
    candidate_frames = 0
    last_committed = ""
    release_frames = release_needed
    latest_conf = 0.0
    latest_letter = ""
    recent_probs: deque = deque(maxlen=int(cfg.get("smooth_frames", 5)))
    started = time.monotonic()

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

            valid_prediction = False
            latest_letter = ""
            latest_conf = 0.0

            if result.hand_landmarks:
                hand = result.hand_landmarks[0]
                draw_hand(frame, hand)
                points = np.array([[lm.x, lm.y, lm.z] for lm in hand], dtype=np.float32)
                # ignore hands entering/leaving the frame (stops random Q/P letters)
                near_edge = (points[:, 0].min() < 0.02 or points[:, 0].max() > 0.98 or
                             points[:, 1].min() < 0.02 or points[:, 1].max() > 0.98)
                # The personal model is trained with fallback_normalize(), so use
                # the exact same feature preparation at inference time.
                features = fallback_normalize(points) if using_personal else normalize_points(points, normalizers)
                x = torch.from_numpy(features).float().unsqueeze(0)

                with torch.no_grad():
                    logits = model(x)
                    logits[0, ~letter_mask] = float("-inf")   # ignore digits 0-9
                    recent_probs.append(torch.softmax(logits, dim=-1)[0])
                    probs = torch.stack(list(recent_probs)).mean(dim=0)   # smooth over last few frames
                    conf, idx = torch.max(probs, dim=0)
                    top2 = torch.topk(probs, 2).values
                margin_ok = float(top2[0] - top2[1]) >= 0.3   # model must be clearly sure

                latest_conf = float(conf.item())
                latest_letter = decode_label(encoder, int(idx.item()))
                valid_prediction = (latest_letter.isalpha() and len(latest_letter) == 1
                                    and latest_conf >= threshold and margin_ok and not near_edge)

                if valid_prediction:
                    if latest_letter == candidate:
                        candidate_frames += 1
                    else:
                        candidate = latest_letter
                        candidate_frames = 1

                    if latest_letter != last_committed:
                        release_frames = release_needed
                    elif latest_letter == last_committed:
                        release_frames = max(0, release_frames - 1)

                    if candidate_frames >= stable_needed and release_frames >= release_needed:
                        reply = send_letter(latest_letter, latest_conf)
                        online = reply is not None
                        spelled = reply if online else spelled + latest_letter
                        last_committed = latest_letter
                        candidate_frames = 0
                        release_frames = 0
                        print(f"[Fingerspell] Registered {latest_letter} -> {spelled}")
                else:
                    candidate = ""
                    candidate_frames = 0
                    release_frames = min(release_needed, release_frames + 1)
                    # a pause / relaxed hand between two identical letters allows
                    # double letters (e.g. HELLO, BOOK) without moving the hand away
                    if release_frames >= release_needed:
                        last_committed = ""
            else:
                recent_probs.clear()
                candidate = ""
                candidate_frames = 0
                release_frames = min(release_needed, release_frames + 1)
                if release_frames >= release_needed:
                    last_committed = ""

            # pick up changes made with Unit A's buttons (UNDO / SPACE / SEND)
            now = time.monotonic()
            if now >= next_sync:
                reply = send_key("get")
                online = reply is not None
                if online:
                    spelled = reply
                next_sync = now + (0.5 if online else 3.0)

            current_word = spelled.split(" ")[-1]
            sentence_preview = spelled
            mode = f"FINGERSPELL | {latest_letter or '-'} {latest_conf:.0%}"
            cv2.rectangle(frame, (0, 0), (frame.shape[1], 115), (20, 20, 20), -1)
            cv2.putText(frame, mode, (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (0, 255, 0), 2)
            cv2.putText(frame, f"Word: {current_word or '-'}", (15, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (255,255,255), 2)
            cv2.putText(frame, f"Sentence: {sentence_preview[-65:] or '-'}", (15, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255,255,255), 2)
            link = "Unit A link: backend OK" if online else "Backend NOT running - start Backend/main.py"
            cv2.putText(frame, link, (15, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                        (0, 255, 0) if online else (0, 0, 255), 1)
            cv2.putText(frame, "SPACE space | BKSP undo | ENTER speak | C clear | Q quit",
                        (12, frame.shape[0]-18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255,255,255), 1)

            cv2.imshow(str(cfg.get("window_name", "Person 1 - ASL Fingerspelling")), frame)
            key = cv2.waitKey(1) & 0xFF

            if key in (ord("q"), 27):
                break
            if key == ord("c"):
                reply = send_key("clear")
                spelled = reply if reply is not None else ""
                last_committed = ""
            elif key == 8:  # Backspace = UNDO one letter
                reply = send_key("undo")
                spelled = reply if reply is not None else spelled[:-1]
            elif key == 32:  # Space
                reply = send_key("space")
                if reply is not None:
                    spelled = reply
                elif spelled and not spelled.endswith(" "):
                    spelled += " "
                last_committed = ""
            elif key in (10, 13):  # Enter = SEND (speak on Unit B)
                reply = send_key("send")
                if reply is not None:
                    spelled = reply
                    last_committed = ""
                else:
                    print("[Fingerspell] Not sent - Backend/main.py is not running.")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
