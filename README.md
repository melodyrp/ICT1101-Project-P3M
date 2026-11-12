## Setup (everyone, first time only)
1. Create the venv: `python -m venv venv`
2. Activate it: `venv\Scripts\activate`
3. Install packages: `python -m pip install -r requirements.txt`

## Speech (Julia)
Whisper speech-to-text and Piper text-to-speech.
1. `cd Speech`
2. Run `python -m piper.download_voices en_US-lessac-medium`
3. `cd ..` to go back to the main folder

**Windows note:** Whisper may be blocked by Smart App Control
("An Application Control policy has blocked this file").
- Option A: turn it off in Windows Security → App & browser control → Smart App Control.
  It can be turned back on later.
- Option B: leave it on. speech.py automatically switches to Google speech
  recognition instead (needs internet). Run `python -m pip install SpeechRecognition`.


## Notes
- Use `python -m pip` instead of `pip`. Windows may block `pip.exe`.
- Don't commit `venv/`, voice files (`.onnx`), `.wav` files or `arduino_secrets.h`. These are already in `.gitignore`.
- If someone adds a new package, run `python -m pip freeze > requirements.txt` and commit it, then everyone runs Setup step 3 again.