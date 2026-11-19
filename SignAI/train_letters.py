"""Train a personal ASL A-Z MLP from data collected by collect_letters.py.

The resulting model files are saved inside SignAI/models/ and are automatically
preferred by fingerspell_team.py when present.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

import joblib
import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.preprocessing import LabelEncoder
from torch.utils.data import DataLoader, TensorDataset

HERE = Path(__file__).resolve().parent
DEFAULT_DATA = HERE / "data" / "personal_letters.csv"
MODELS_DIR = HERE / "models"
MODEL_PATH = MODELS_DIR / "my_fingerspell_model.pth"
ENCODER_PATH = MODELS_DIR / "my_fingerspell_label_encoder.pkl"
META_PATH = MODELS_DIR / "my_fingerspell_model_meta.json"
CONFUSION_PATH = MODELS_DIR / "my_fingerspell_confusion_matrix.csv"


class PersonalMLP(nn.Module):
    def __init__(self, num_classes: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(63, 128),
            nn.ReLU(),
            nn.Dropout(0.15),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Dropout(0.10),
            nn.Linear(64, num_classes),
        )

    def forward(self, x):
        return self.net(x)


def load_dataset(path: Path):
    labels, sessions, features = [], [], []
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        feature_cols = [f"f{i}" for i in range(63)]
        for row in reader:
            labels.append(row["label"].upper())
            sessions.append(row.get("session", "1"))
            features.append([float(row[c]) for c in feature_cols])
    return np.asarray(features, dtype=np.float32), np.asarray(labels), np.asarray(sessions)


def set_seed(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def save_confusion(path: Path, cm: np.ndarray, classes: list[str]):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["actual\\predicted", *classes])
        for label, row in zip(classes, cm):
            w.writerow([label, *row.tolist()])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not args.data.exists():
        raise FileNotFoundError(f"Dataset not found: {args.data}\nRun collect_letters.py first.")

    set_seed(args.seed)
    X, labels, sessions = load_dataset(args.data)
    if len(X) == 0:
        raise RuntimeError("Dataset is empty.")

    expected = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    present = set(labels.tolist())
    missing = sorted(expected - present)
    if missing:
        raise RuntimeError(
            "Collect all A-Z classes before training. Missing: " + ", ".join(missing)
        )

    encoder = LabelEncoder()
    y = encoder.fit_transform(labels)

    unique_sessions = np.unique(sessions)
    if len(unique_sessions) >= 2:
        splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=args.seed)
        train_idx, val_idx = next(splitter.split(X, y, groups=sessions))
        split_note = f"group split by collection session ({len(unique_sessions)} sessions)"
    else:
        train_idx, val_idx = train_test_split(
            np.arange(len(X)), test_size=0.20, random_state=args.seed, stratify=y
        )
        split_note = "random frame split (only one session; validation may be optimistic)"

    X_train, X_val = X[train_idx], X[val_idx]
    y_train, y_val = y[train_idx], y[val_idx]

    train_ds = TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train).long())
    val_x = torch.from_numpy(X_val)
    val_y = torch.from_numpy(y_val).long()
    loader = DataLoader(train_ds, batch_size=args.batch, shuffle=True)

    model = PersonalMLP(num_classes=len(encoder.classes_))
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-5)
    criterion = nn.CrossEntropyLoss()

    best_acc = -1.0
    best_state = None

    print(f"[Train] Samples: {len(X)}")
    print(f"[Train] Classes: {len(encoder.classes_)}")
    print(f"[Train] Sessions: {', '.join(map(str, unique_sessions))}")
    print(f"[Train] Validation: {split_note}")
    print(f"[Train] Train/val: {len(train_idx)}/{len(val_idx)}")

    for epoch in range(1, args.epochs + 1):
        model.train()
        running_loss = 0.0
        for xb, yb in loader:
            optimizer.zero_grad()
            logits = model(xb)
            loss = criterion(logits, yb)
            loss.backward()
            optimizer.step()
            running_loss += float(loss.item()) * len(xb)

        model.eval()
        with torch.no_grad():
            val_logits = model(val_x)
            val_pred = torch.argmax(val_logits, dim=1)
            val_acc = float((val_pred == val_y).float().mean().item())

        if val_acc > best_acc:
            best_acc = val_acc
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

        if epoch == 1 or epoch % 5 == 0 or epoch == args.epochs:
            avg_loss = running_loss / max(1, len(train_ds))
            print(f"[Train] Epoch {epoch:03d}/{args.epochs} loss={avg_loss:.4f} val_acc={val_acc:.2%}")

    assert best_state is not None
    model.load_state_dict(best_state)
    model.eval()

    with torch.no_grad():
        pred = torch.argmax(model(val_x), dim=1).numpy()
    final_acc = accuracy_score(y_val, pred)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), MODEL_PATH)
    joblib.dump(encoder, ENCODER_PATH)

    classes = [str(x) for x in encoder.classes_]
    cm = confusion_matrix(y_val, pred, labels=np.arange(len(classes)))
    save_confusion(CONFUSION_PATH, cm, classes)

    meta = {
        "model": "63-128-64-AZ MLP",
        "normalization": "wrist-centred, scaled by maximum landmark distance",
        "samples": int(len(X)),
        "classes": classes,
        "sessions": [str(x) for x in unique_sessions.tolist()],
        "validation_split": split_note,
        "validation_accuracy": float(final_acc),
        "best_validation_accuracy": float(best_acc),
        "epochs": int(args.epochs),
        "note": "J and Z are motion-based ASL letters and remain a limitation of static-frame classification.",
    }
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print("\n[Train] Final validation accuracy: {:.2%}".format(final_acc))
    print(classification_report(y_val, pred, target_names=classes, zero_division=0))
    print(f"[Train] Saved model: {MODEL_PATH}")
    print(f"[Train] Saved labels: {ENCODER_PATH}")
    print(f"[Train] Saved metadata: {META_PATH}")
    print(f"[Train] Saved confusion matrix: {CONFUSION_PATH}")
    print("[Train] fingerspell_team.py will automatically use your personal model now.")


if __name__ == "__main__":
    main()
