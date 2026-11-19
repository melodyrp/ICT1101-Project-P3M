"""Create ``src/live_demo_team.py`` from the upstream 250-sign demo.

Run this script from the root of the upstream translator repository *after*
copying person1_bridge.py into its src folder and person1_config.json into its
root.  The ML/preprocessing/model code is not changed.
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src" / "live_demo_transformer.py"
DST = ROOT / "src" / "live_demo_team.py"

IMPORT = (
    "from person1_bridge import observe_sentence_from_locals as _p1_observe, "
    "send_sentence_from_locals as _p1_send_sentence\n"
)


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"Missing {SRC}")
    lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)
    if not any("person1_bridge" in x for x in lines):
        # Upstream file uses ordinary imports; put bridge before them.
        lines.insert(0, IMPORT)

    wait = re.compile(r"^(?P<indent>\s*)(?P<var>[A-Za-z_]\w*)\s*=\s*cv2\.waitKey\s*\(")
    patched = False
    for i, line in enumerate(lines):
        m = wait.search(line)
        if not m:
            continue
        indent, var = m.group("indent"), m.group("var")
        lines[i + 1:i + 1] = [
            f"{indent}# Person 1 -> team backend integration\n",
            f"{indent}_p1_observe(locals())\n",
            f"{indent}if {var} in (10, 13):  # Enter = finalise/send sentence\n",
            f"{indent}    _p1_send_sentence(locals())\n",
        ]
        patched = True
        break
    if not patched:
        raise SystemExit("Could not find cv2.waitKey assignment; upstream demo changed.")
    DST.write_text("".join(lines), encoding="utf-8")
    print(f"Created {DST}")
    print("Run: python .\\src\\live_demo_team.py")
    print("Added: ENTER sends the current sentence to Backend/main.py")


if __name__ == "__main__":
    main()
