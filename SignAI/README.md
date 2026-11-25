# Person 1 — Sign Language AI

This folder is the integration point for Person 1.

## What the final Person 1 software does

### Mode 1 — 250-word ASL recognition
External pretrained project: `aymenwnia/ASL-translator`.

Pipeline:

`webcam -> MediaPipe hands/face/pose -> 64-frame Transformer -> supported ASL word -> sentence -> team backend`

The pretrained model supports 250 isolated ASL signs.

### Mode 2 — ASL fingerspelling fallback
External pretrained project: `ronronrivera/real-time-asl-detection`.

Pipeline:

`webcam -> MediaPipe hand landmarks -> pretrained alphabet MLP -> stable letter -> word buffer -> sentence -> team backend`

This allows unsupported English words to be spelled letter-by-letter.

**J and Z are motion-based ASL letters and are expected to be less reliable in a static-frame alphabet model.**

---

## Important folder layout

Keep external model repositories OUTSIDE the team Git repository:

```text
PROJECT/
├── ICT1101-Project-P3M/          <- team GitHub repo
│   ├── Backend/
│   ├── SignAI/
│   ├── Speech/
│   └── UnitB/
│
├── sign_lang_trans/              <- 250-word pretrained repo
└── asl_fingerspell_model/        <- alphabet pretrained repo
```

Do not commit the external repositories into the team repo.

---

## One-time setup

Activate your project virtual environment first.

### A. Install 250-word integration

From `ICT1101-Project-P3M\SignAI`:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install_into_translator.ps1 -TranslatorPath "C:\path\to\PROJECT\sign_lang_trans"
```

### B. Install fingerspelling model

From the same folder:

```powershell
.\install_fingerspelling.ps1
```

The installer clones the pretrained alphabet model beside the team repo and installs its requirements.

---

## Run the team backend first

Terminal 1:

```powershell
cd Backend
python fake_unitb.py
```

Terminal 2:

```powershell
cd Backend
python main.py --unita none --tts beep --stt fake
```

For real hardware later, replace fake Unit B / beep TTS with the team's real options.

---

## Launch Person 1

From the team repo root:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\SignAI\run_sign_ai.ps1
```

Choose:

- `1` — 250-word ASL mode
- `2` — fingerspelling A-Z mode

### 250-word mode controls
- `Q` quit
- `C` clear
- `SPACE` sentence spacing / upstream behavior
- `ENTER` send final sentence to Backend

### Fingerspelling controls
- Hold a letter steady until it registers once
- `SPACE` finish the current spelled word
- `BACKSPACE` delete the last letter
- `C` clear
- `ENTER` finish the current word and send the full sentence
- `Q` / `ESC` quit

Example:

```text
H -> E -> L -> P
SPACE
M -> E
ENTER
```

sends:

```text
HELP ME
```

to `Backend/sign_receiver.py`, where the team's existing controller sends it to TTS / Unit B.

---

## Accuracy testing

Use `accuracy_template.csv`, record actual/predicted/confidence, then:

```powershell
python .\SignAI\accuracy_report.py .\SignAI\accuracy_results.csv
```

Test word mode and fingerspelling separately.

---

## Files in this folder

- `install_into_translator.ps1` — installs team backend bridge into 250-word repo
- `patch_demo.py` — creates `live_demo_team.py`
- `person1_bridge.py` — sends 250-word sentence to Backend
- `person1_config.json` — 250-word backend config
- `install_fingerspelling.ps1` — installs external pretrained alphabet model
- `fingerspell_team.py` — Person 1 fingerspelling webcam mode
- `fingerspell_bridge.py` — sends spelled sentence to Backend
- `fingerspelling_config.json` — fingerspelling thresholds / paths
- `run_sign_ai.ps1` — menu to launch word or spelling mode
- `accuracy_report.py` — accuracy calculator
- `accuracy_template.csv` — test template
- `send_test_sentence.py` — backend smoke test

## Scope statement for report

The prototype recognises a fixed vocabulary of 250 isolated ASL signs using a pretrained Transformer. For words outside this vocabulary, a pretrained ASL fingerspelling model provides an A-Z fallback. Recognised text is sent to the existing backend, where TTS and Unit B provide spoken output.
