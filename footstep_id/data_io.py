"""Read both the user's legacy data(7).zip and the new UNO Q session folders."""
from pathlib import Path
from io import BytesIO
import json
from zipfile import ZipFile
import pandas as pd
import numpy as np
from .config import LABELS

SENSORS = ("microphone", "piezo", "mpu6050")


def person_label(raw):
    name = str(raw).strip().lower().replace("_", " ")
    if name in ("silent", "silence", "no footsteps", "no-footsteps"):
        return "No Footsteps"
    for label in LABELS:
        if label.lower() == name:
            return label
    raise ValueError(f"Unrecognized label directory {raw!r}; use {LABELS}")


def from_frame(sensor, frame):
    if sensor in ("microphone", "piezo"):
        out = frame["raw"].to_numpy(dtype=np.float64, copy=True)
        out[out == -32768] = np.nan
        return out
    if all(key in frame for key in ("x_raw", "y_raw", "z_raw")):
        out = frame[["x_raw", "y_raw", "z_raw"]].to_numpy(dtype=np.float64, copy=True)
        out[out == -32768] = np.nan
        return out / 16384.0
    if all(key in frame for key in ("x_g", "y_g", "z_g")):
        # Read already converted physical units if no raw accelerometer values exist.
        return frame[["x_g", "y_g", "z_g"]].to_numpy(dtype=np.float64, copy=True)
    raise ValueError("MPU CSV requires x_raw,y_raw,z_raw or x_g,y_g,z_g")


def _decode_csv(sensor, data):
    if not data:
        return None
    try:
        frame = pd.read_csv(BytesIO(data))
        if frame.empty:
            return None
        return from_frame(sensor, frame)
    except (pd.errors.EmptyDataError, ValueError, KeyError) as exc:
        print(f"WARNING: ignoring invalid {sensor}.csv: {exc}")
        return None


def load_trial_folder(trial_dir):
    trial = Path(trial_dir)
    if not trial.is_dir():
        raise FileNotFoundError(trial)
    return {sensor: _decode_csv(sensor, (trial / f"{sensor}.csv").read_bytes())
            if (trial / f"{sensor}.csv").exists() else None
            for sensor in SENSORS}


def iter_folder_trials(dataset_root):
    root = Path(dataset_root)
    if not root.is_dir():
        raise FileNotFoundError(root)
    found = False
    for classdir in sorted(root.iterdir()):
        if not classdir.is_dir():
            continue
        try:
            label = person_label(classdir.name)
        except ValueError:
            continue
        for session in sorted(classdir.iterdir()):
            if not session.is_dir() or not (session / "microphone.csv").exists():
                continue
            found = True
            audio_file = str(session / "audio.wav") if (session / "audio.wav").exists() else None
            meta_path = session / "metadata.json"
            if meta_path.exists():
                try:
                    metadata = json.loads(meta_path.read_text())
                    # Strong rule: never train on a mostly interpolated acoustic WAV.
                    if metadata.get("audio_usable_for_training") is False:
                        print(f"WARNING: excluding invalid WAV (dropouts): {audio_file}")
                        audio_file = None
                except (OSError, ValueError) as exc:
                    print(f"WARNING: cannot read metadata for {session}: {exc}")
            yield {"id": str(session.resolve()), "label": label,
                   "signals": load_trial_folder(session), "audio_file": audio_file}
    if not found:
        raise ValueError(f"No sessions found in {root}. Need <root>/<person>/<session>/microphone.csv")


def iter_zip_trials(zip_path):
    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        for mic_path in sorted(p for p in names if p.endswith("/microphone.csv")):
            base = mic_path.rsplit("/", 1)[0]
            parts = Path(base).parts
            if len(parts) < 2:
                continue
            try:
                label = person_label(parts[-2])
            except ValueError:
                continue
            signals = {sensor: _decode_csv(sensor, archive.read(base + "/" + sensor + ".csv"))
                       if base + "/" + sensor + ".csv" in names else None
                       for sensor in SENSORS}
            yield {"id": base, "label": label, "signals": signals, "audio_file": None}


def iter_trials(source):
    path = Path(source)
    if path.is_file() and path.suffix.lower() == ".zip":
        yield from iter_zip_trials(path)
    elif path.is_dir():
        yield from iter_folder_trials(path)
    else:
        raise ValueError("Pass the dataset directory or old data(7).zip")
