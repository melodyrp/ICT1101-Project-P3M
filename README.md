## Setup (everyone, first time only)
1. Create the venv: `python -m venv venv`
2. Activate it: `venv\Scripts\activate`
3. Install packages: `python -m pip install -r requirements.txt`

## Speech (Julia)
Whisper speech-to-text and Piper text-to-speech.
1. `cd Speech`
2. Run `python -m piper.download_voices en_US-lessac-medium`
3. `cd ..` to go back to the main folder

## Notes
- Use `python -m pip` instead of `pip`. Windows may block `pip.exe`.
- Don't commit `venv/`, voice files (`.onnx`), `.wav` files or `arduino_secrets.h`. These are already in `.gitignore`.
- If someone adds a new package, run `python -m pip freeze > requirements.txt` and commit it, then everyone runs Setup step 3 again.