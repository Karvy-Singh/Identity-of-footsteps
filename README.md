# Multi-Sensor Footstep Identification

Controlled footstep identification using low-cost acoustic, vibration, and motion sensors.

Inspired by the recent study published in the journal Sensors (Volume 26, Issue 18, Article 5736, September 2026): 

https://www.mdpi.com/1424-8220/26/18/5736

## System
- **Hardware:** Arduino UNO Q, SEN0487 microphone on A0, conditioned piezo sensor on A1, and MPU6050 over I2C (`0x68`).
- **Pass 1:** 10 s audio-only WAV capture at a nominal 6 kHz.
- **Pass 2:** a separate 10 s capture of microphone and piezo at 500 Hz plus MPU6050 acceleration at 200 Hz.
- **Session files:** `audio.wav`, `microphone.csv`, `piezo.csv`, `mpu6050.csv`, and `metadata.json`.

The two passes are sequential, **not synchronized recordings of the same footsteps**. Missing-sample diagnostics must be checked before training; WAV sessions with excessive audio dropout are rejected.

## Classification Pipeline

1. Extract numerical features from 2 s windows with a 1 s stride.
2. Train independent standardized RBF SVMs (`C=10`) for microphone, piezo, and acceleration data.
3. Resample 6 kHz audio to 16 kHz, extract PANNs CNN14 embeddings, and train a fourth identity SVM.
4. Fuse available model scores using initial weights `1.0/1.0/1.0/0.5` and optionally smooth five consecutive predictions by majority vote.
5. CNN14 is used only as a feature extractor. Generic AudioSet labels do not identify a person; the audio SVM requires clean, participant-labeled recordings.

## Quick Start

```sh
pip install -r requirements.txt
# Required only for the CNN14 audio branch:
pip install -r requirements-audio.txt

# Train all models, or append --sensors-only
python -m footstep_id.train_all ./footstep_dataset
```

For UNO Q acquisition, load `sketch/sketch.ino` and `main.py` in Arduino App Lab. Set `PERSON`, `APP_NAME`, `THINGSPEAK_CHANNEL_ID`, and `THINGSPEAK_WRITE_KEY` in `main.py`, then run the app. Use `UPLOAD_ONLY = True` to retry saved sessions without recording again.

## ThingSpeak Transfer

Completed sessions can be compressed, checksummed, split into chunks, and uploaded to a **private eight-field ThingSpeak channel**. ThingSpeak is used for session transport, not real-time waveform streaming. Keep API keys and labeled gait/audio data private.

```sh
export THINGSPEAK_CHANNEL_ID=1234567
export THINGSPEAK_READ_KEY=your_private_read_key

python -m footstep_id.thingspeak_cli list
python -m footstep_id.thingspeak_cli pull --latest
python -m footstep_id.thingspeak_cli classify --latest
```

Local sessions are stored under `footstep_dataset/<label>/<session_id>/`; restored cloud sessions default to `downloaded_sessions/`.
