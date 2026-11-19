"""Create simple Person 1 accuracy metrics from a CSV of webcam trials.

CSV columns: actual,predicted,confidence,person,attempt
"""
from __future__ import annotations
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "accuracy_results.csv")
if not path.exists():
    raise SystemExit(f"Missing {path}")
rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
if not rows:
    raise SystemExit("CSV has no data rows")

correct = sum(r["actual"].strip().lower() == r["predicted"].strip().lower() for r in rows)
lines = [f"Total attempts: {len(rows)}", f"Correct: {correct}", f"Overall accuracy: {correct/len(rows)*100:.2f}%", ""]
by_sign = defaultdict(list)
for r in rows:
    by_sign[r["actual"].strip().lower()].append(r)
lines.append("Per-sign accuracy:")
for sign in sorted(by_sign):
    group = by_sign[sign]
    c = sum(x["actual"].strip().lower() == x["predicted"].strip().lower() for x in group)
    lines.append(f"  {sign}: {c}/{len(group)} = {c/len(group)*100:.1f}%")

confusions = Counter((r["actual"].strip().lower(), r["predicted"].strip().lower()) for r in rows if r["actual"].strip().lower() != r["predicted"].strip().lower())
if confusions:
    lines += ["", "Most common confusions:"]
    for (actual, pred), n in confusions.most_common(10):
        lines.append(f"  {actual} -> {pred}: {n}")

out = path.with_name("accuracy_summary.txt")
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
print(f"\nSaved {out}")
