# ICT1101 Project Setup

Follow these instructions after cloning the repository for the first time.

---

## Setup (everyone, first time only)

Open PowerShell or the VS Code terminal inside the main project folder:

```text
ICT1101-Project-P3M
```

### 1. Create the virtual environment

```powershell
python -m venv venv
```

### 2. Allow PowerShell scripts

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 3. Activate the virtual environment

```powershell
.\venv\Scripts\Activate.ps1
```

You should now see:

```text
(venv)
```

at the start of the terminal.

### 4. Upgrade pip

```powershell
python -m pip install --upgrade pip
```

### 5. Install the main project requirements

```powershell
python -m pip install -r requirements.txt
```

### 6. Install the SignAI requirements

```powershell
python -m pip install -r .\SignAI\requirements_sign_ai.txt
```

---

# Speech (Julia)

Whisper speech-to-text and Piper text-to-speech.

### 1. Go to the Speech folder

```powershell
cd Speech
```

### 2. Download the Piper voice

```powershell
python -m piper.download_voices en_US-lessac-medium
```

### 3. Go back to the main project folder

```powershell
cd ..
```

### Windows note

Whisper may be blocked by Smart App Control:

```text
An Application Control policy has blocked this file
```

There are two options.

**Option A:** Turn off Smart App Control in:

```text
Windows Security
→ App & browser control
→ Smart App Control
```

It can be turned back on later.

**Option B:** Leave Smart App Control enabled.

`speech.py` automatically switches to Google Speech Recognition instead. This requires an internet connection.

If required, install SpeechRecognition:

```powershell
python -m pip install SpeechRecognition
```

---

# Sign Language AI

The SignAI component uses the webcam to recognise **ASL fingerspelling A-Z**.

The trained A-Z model is already included in the repository.

You do **not** need to collect data or train the model again.

The SignAI flow is:

```text
Webcam
→ MediaPipe hand landmarks
→ trained A-Z model
→ recognised letters
→ words / sentence
→ Backend
→ Text-to-Speech
→ Unit B
```

---

## SignAI first-time setup

Make sure you have already completed the main Setup section and that:

```text
(venv)
```

appears in your terminal.

### 1. Allow PowerShell scripts

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 2. Go into the SignAI folder

```powershell
cd .\SignAI
```

### 3. Run the fingerspelling installer

```powershell
.\install_fingerspelling.ps1
```

Wait until the installation finishes.

This installs the additional fingerspelling support files and dependencies required by SignAI.

### 4. Go back to the main project folder

```powershell
cd ..
```

### 5. Download the MediaPipe Hand Landmarker model

Run:

```powershell
Invoke-WebRequest -Uri "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task" -OutFile ".\SignAI\hand_landmarker.task"
```

---

## Check that SignAI is ready

Run:

```powershell
Test-Path .\SignAI\models\my_fingerspell_model.pth
```

It should return:

```text
True
```

Then run:

```powershell
Test-Path .\SignAI\models\my_fingerspell_label_encoder.pkl
```

It should return:

```text
True
```

Then run:

```powershell
Test-Path .\SignAI\hand_landmarker.task
```

It should also return:

```text
True
```

All three should return:

```text
True
```

If they do, the SignAI setup is complete.

---

# Running SignAI + Backend + Unit B

For the Sign Language system, open **3 terminals**.

Keep all three terminals running at the same time.

```text
Terminal 1 → Fake Unit B
Terminal 2 → Backend
Terminal 3 → SignAI Camera
```

---

## Terminal 1 — Fake Unit B

Open a new terminal inside the main project folder.

### 1. Allow PowerShell scripts

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 2. Activate the virtual environment

```powershell
.\venv\Scripts\Activate.ps1
```

### 3. Go to Backend

```powershell
cd .\Backend
```

### 4. Start Fake Unit B

```powershell
python fake_unitb.py
```

Leave this terminal running.

You should see something similar to:

```text
[fake Unit B] WIFI READY  127.0.0.1  port 5555
```

---

## Terminal 2 — Backend

Open another terminal inside the main project folder.

### 1. Allow PowerShell scripts

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 2. Activate the virtual environment

```powershell
.\venv\Scripts\Activate.ps1
```

### 3. Go to Backend

```powershell
cd .\Backend
```

### 4. Start the Backend

```powershell
python main.py --unita none --tts beep --stt fake
```

Leave this terminal running.

You should see:

```text
[sign] listening for Person 1 on 127.0.0.1:5560
```

This means the backend is ready to receive recognised sentences from SignAI.

---

## Terminal 3 — SignAI Camera

Open another terminal inside the main project folder.

### 1. Allow PowerShell scripts

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 2. Activate the virtual environment

```powershell
.\venv\Scripts\Activate.ps1
```

### 3. Start the fingerspelling camera

```powershell
python .\SignAI\fingerspell_team.py
```

The webcam should open.

You should see something similar to:

```text
[Fingerspell] Using PERSONAL model:
...\SignAI\models\my_fingerspell_model.pth
```

This confirms that the trained A-Z model included in the repository is being used.

---

# SignAI Camera Controls

Show an ASL fingerspelling letter to the webcam and hold it steady until the letter registers.

### Controls

```text
SPACE
```

Finish the current word.

```text
BACKSPACE
```

Delete the last recognised letter.

```text
C
```

Clear the current sentence.

```text
ENTER
```

Finish the current word and send the complete sentence to the backend.

```text
Q
```

or

```text
ESC
```

Close the camera.

---

## Example

Sign:

```text
C → A → T → S
```

Press:

```text
SPACE
```

Then sign:

```text
A → R → E
```

Press:

```text
SPACE
```

Then sign:

```text
C → U → T → E
```

Press:

```text
ENTER
```

The system sends:

```text
CATS ARE CUTE
```

The complete flow is:

```text
Camera
→ CATS ARE CUTE
→ Backend
→ Text-to-Speech
→ Fake Unit B
```

---

# Expected Output

After pressing `ENTER`, the Backend terminal should show something similar to:

```text
[sign] received from 127.0.0.1: 'CATS ARE CUTE'
[sign] queued "CATS ARE CUTE"
```

The Fake Unit B terminal should then show something similar to:

```text
[fake Unit B] SCREEN: "CATS ARE CUTE"
[fake Unit B] SPEAKING
[fake Unit B] FINISHED
```

If this happens, the complete:

```text
SignAI
→ Backend
→ TTS
→ Unit B
```

connection is working.

---

# If SignAI Does Not Reach the Backend

Keep **Terminal 1** and **Terminal 2** running.

Open another terminal inside the main project folder.

### 1. Allow PowerShell scripts

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 2. Activate the virtual environment

```powershell
.\venv\Scripts\Activate.ps1
```

### 3. Send a test sentence

```powershell
python .\SignAI\send_test_sentence.py "REMOTE TEST"
```

If the connection is working, you should see:

```text
Backend reply: OK
```

The Backend terminal should receive:

```text
REMOTE TEST
```

and Fake Unit B should display it.

---

# Important Notes

Use:

```powershell
python -m pip
```

instead of only:

```text
pip
```

because Windows may block `pip.exe`.

Do not commit:

```text
venv/
*.onnx
*.wav
arduino_secrets.h
```

These should already be included in `.gitignore`.

If someone adds a new Python package, update `requirements.txt` using:

```powershell
python -m pip freeze > requirements.txt
```

Commit the updated `requirements.txt`.

Everyone else should then run:

```powershell
python -m pip install -r requirements.txt
```

again.

---

# SignAI Important Note

The current SignAI implementation uses **ASL fingerspelling only**.

You do **not** need to clone:

```text
sign_lang_trans
```

You do **not** need to run:

```text
install_into_translator.ps1
```

You do **not** need to run:

```text
run_sign_ai.ps1
```

You do **not** need to run:

```text
collect_letters.py
```

or:

```text
train_letters.py
```

for normal use.

The trained model is already included in the repository.

The only SignAI program that needs to be launched for normal use is:

```powershell
python .\SignAI\fingerspell_team.py
```