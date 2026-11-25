# Person 1 — Sign Language AI

This folder contains the **Person 1 Sign Language AI integration** for the project.

The current implementation uses **ASL fingerspelling recognition (A–Z)**. A webcam captures the user's hand signs, MediaPipe extracts hand landmarks, and the trained fingerspelling model predicts individual letters.

Recognised letters are combined into words and sentences before being sent to the team's backend.

---

## What the Person 1 software does

### ASL Fingerspelling Recognition

Pipeline:

```text
Webcam
↓
MediaPipe Hand Landmarker
↓
21 hand landmarks
↓
Trained A–Z fingerspelling model
↓
Predicted letters
↓
Word / sentence buffer
↓
Backend
↓
Text-to-Speech
↓
Unit B
```

The model recognises the **26 alphabet letters A–Z**.

The model stored inside this repository was personally trained for this project.

> **Note:** J and Z normally involve movement in ASL, so they may be less reliable because the current classifier mainly uses hand landmarks from individual frames.

---

# Folder Structure

The main Person 1 files are located inside:

```text
ICT1101-Project-P3M/
│
├── Backend/
│   ├── main.py
│   ├── sign_receiver.py
│   ├── fake_unitb.py
│   └── ...
│
├── SignAI/
│   ├── fingerspell_team.py
│   ├── fingerspell_bridge.py
│   ├── fingerspelling_config.json
│   ├── install_fingerspelling.ps1
│   ├── send_test_sentence.py
│   ├── requirements_sign_ai.txt
│   │
│   ├── models/
│   │   ├── my_fingerspell_model.pth
│   │   ├── my_fingerspell_label_encoder.pkl
│   │   └── ...
│   │
│   └── ...
│
├── Speech/
├── UnitA/
├── UnitB/
│
└── requirements.txt
```

The trained fingerspelling model is already included in:

```text
SignAI/models/
```

The user does **not** need to train the model again.

---

# Fresh Clone Setup

Follow these instructions if you have just cloned the repository onto a new computer.

## 1. Clone the Repository

Open PowerShell in the folder where you want the project.

Run:

```powershell
git clone <GROUP_GITHUB_REPOSITORY_URL>
```

Enter the repository:

```powershell
cd ICT1101-Project-P3M
```

If using VS Code:

```powershell
code .
```

---

# 2. Create a Virtual Environment

From the root of the repository:

```powershell
python -m venv .venv
```

Allow PowerShell scripts for the current terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

The terminal should now show:

```text
(.venv)
```

---

# 3. Install Python Requirements

Upgrade pip:

```powershell
python -m pip install --upgrade pip
```

Install the project requirements:

```powershell
pip install -r requirements.txt
```

Install the SignAI requirements:

```powershell
pip install -r .\SignAI\requirements_sign_ai.txt
```

The main SignAI dependencies include:

- OpenCV
- MediaPipe
- PyTorch
- NumPy
- Joblib
- Scikit-learn

---

# 4. Install Fingerspelling Dependencies

Go into the SignAI folder:

```powershell
cd .\SignAI
```

Run:

```powershell
.\install_fingerspelling.ps1
```

This installs the additional files and dependencies required by the fingerspelling system.

After it finishes, return to the repository root:

```powershell
cd ..
```

---

# 5. Download the MediaPipe Hand Landmarker

The camera system requires the MediaPipe Hand Landmarker model.

From the repository root, run:

```powershell
Invoke-WebRequest -Uri "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task" -OutFile ".\SignAI\hand_landmarker.task"
```

The file should now exist at:

```text
SignAI/hand_landmarker.task
```

---

# 6. Check Required Model Files

Run:

```powershell
Test-Path .\SignAI\models\my_fingerspell_model.pth
```

It should return:

```text
True
```

Then:

```powershell
Test-Path .\SignAI\models\my_fingerspell_label_encoder.pkl
```

It should return:

```text
True
```

Then:

```powershell
Test-Path .\SignAI\hand_landmarker.task
```

It should also return:

```text
True
```

If all three return `True`, Person 1 is ready to run.

---

# Running the Complete System

The test setup requires **three terminals**:

```text
Terminal 1 → Fake Unit B
Terminal 2 → Backend
Terminal 3 → Sign Language Camera
```

Keep all three terminals running at the same time.

---

## Terminal 1 — Start Fake Unit B

Open a terminal from the repository root.

Allow PowerShell scripts:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Enter the Backend folder:

```powershell
cd .\Backend
```

Start Fake Unit B:

```powershell
python fake_unitb.py
```

Leave this terminal running.

You should see something similar to:

```text
[fake Unit B] WIFI READY  127.0.0.1  port 5555
```

---

## Terminal 2 — Start the Backend

Open another terminal from the repository root.

Run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Enter the Backend folder:

```powershell
cd .\Backend
```

Start the backend:

```powershell
python main.py --unita none --tts beep --stt fake
```

Leave this terminal running.

The backend should display:

```text
[sign] listening for Person 1 on 127.0.0.1:5560
```

This means the backend is ready to receive recognised sentences from Person 1.

---

## Terminal 3 — Start the Fingerspelling Camera

Open a third terminal from the repository root.

Run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Start Person 1:

```powershell
python .\SignAI\fingerspell_team.py
```

The webcam window should open.

The terminal should display something similar to:

```text
[Fingerspell] Using PERSONAL model:
...\SignAI\models\my_fingerspell_model.pth
```

This confirms that the program is using the trained fingerspelling model included with the project.

---

# Fingerspelling Controls

Hold an ASL letter in front of the webcam until it registers.

The available controls are:

- `SPACE` — finish the current word
- `BACKSPACE` — delete the most recent letter
- `C` — clear the current sentence
- `ENTER` — finish the current word and send the full sentence to the backend
- `Q` or `ESC` — quit the program

---

## Example

Sign:

```text
H → E → L → P
```

Press:

```text
SPACE
```

Then sign:

```text
M → E
```

Press:

```text
ENTER
```

The sentence:

```text
HELP ME
```

is sent to the backend.

The full pipeline becomes:

```text
ASL hand signs
↓
Webcam
↓
MediaPipe hand landmarks
↓
Fingerspelling classifier
↓
HELP ME
↓
Backend/sign_receiver.py
↓
Backend controller
↓
Text-to-Speech
↓
Unit B
```

---

# Expected Output

After pressing `ENTER`, Terminal 2 should display something similar to:

```text
[sign] received from 127.0.0.1: 'HELP ME'
[sign] queued "HELP ME"
```

Terminal 1 should then display something similar to:

```text
[fake Unit B] SCREEN: "HELP ME"
[fake Unit B] SPEAKING
[fake Unit B] FINISHED
```

This confirms that the complete Person 1 → Backend → Unit B connection is working.

---

# Backend Connection Test

If the camera opens but pressing `ENTER` does not appear to reach the backend, the connection can be tested without using the camera.

Keep the backend running.

Open another terminal from the repository root.

Activate the virtual environment:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

```powershell
.\.venv\Scripts\Activate.ps1
```

Run:

```powershell
python .\SignAI\send_test_sentence.py "REMOTE TEST"
```

If the connection works, the terminal should display:

```text
Backend reply: OK
```

The backend should receive:

```text
REMOTE TEST
```

and Fake Unit B should display it.

---

# Accuracy Testing

The SignAI folder also contains files for recording and calculating recognition accuracy.

A test CSV can be created using:

```text
accuracy_template.csv
```

After recording the expected sign, predicted sign, and confidence values, run:

```powershell
python .\SignAI\accuracy_report.py .\SignAI\accuracy_results.csv
```

This can be used to calculate the recognition accuracy during testing.

---

# Model Training

The trained model is already included in the repository, so **normal users and testers do not need to retrain it**.

The following files were used during development:

```text
collect_letters.py
train_letters.py
```

`collect_letters.py` was used to collect MediaPipe landmark samples for each alphabet letter.

`train_letters.py` was used to train the A–Z classifier.

These files are only required if the model needs to be retrained in the future.

---

# Important

The current version of Person 1 uses the **fingerspelling model only**.

The following older 250-word ASL integration files are **not required to run the current system**:

```text
install_into_translator.ps1
patch_demo.py
person1_bridge.py
person1_config.json
run_sign_ai.ps1
```

You also do **not** need to clone:

```text
sign_lang_trans
```

for the current Person 1 implementation.

Do not run:

```powershell
.\install_into_translator.ps1
```

and do not use:

```powershell
.\SignAI\run_sign_ai.ps1
```

for the current fingerspelling-only system.

---

# Main Files

### `fingerspell_team.py`

Runs the webcam-based ASL fingerspelling recognition system.

### `fingerspell_bridge.py`

Sends the completed sentence from Person 1 to the backend.

### `fingerspelling_config.json`

Contains Person 1 settings such as:

- Backend IP address
- Backend port
- Camera index
- Confidence threshold
- Stable frame count

### `install_fingerspelling.ps1`

Performs the additional first-time fingerspelling setup.

### `models/my_fingerspell_model.pth`

The trained A–Z classification model.

### `models/my_fingerspell_label_encoder.pkl`

Maps the model output classes to alphabet letters.

### `send_test_sentence.py`

Tests the Person 1 → Backend connection without requiring the camera.

### `accuracy_report.py`

Calculates model accuracy from recorded test results.

### `accuracy_template.csv`

Template for recording recognition test results.

---

# Person 1 Scope Statement

The Person 1 prototype recognises ASL fingerspelling letters from a live webcam feed.

MediaPipe is used to extract hand landmarks, which are passed into a trained A–Z classification model. Stable predictions are converted into letters and combined into words and sentences.

Once the user presses `ENTER`, the completed sentence is sent through a TCP connection to the team's backend. The backend validates and processes the recognised text before sending it to the existing Text-to-Speech and Unit B components for spoken output.

The current implementation therefore provides the following complete flow:

```text
ASL Fingerspelling
→ Recognition
→ Text
→ Backend
→ Text-to-Speech
→ Unit B
```