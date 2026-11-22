"""Inspect adb-pulled sessions before training; warns about timing/dropouts."""
import argparse
import json
from collections import Counter
from pathlib import Path
from .data_io import iter_folder_trials
from .config import LABELS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    args = ap.parse_args()
    trials = list(iter_folder_trials(args.dataset))
    counts = Counter(t["label"] for t in trials)
    print("Sessions:", {name: counts[name] for name in LABELS})
    for t in trials:
        path = Path(t["id"])
        meta_path = path / "metadata.json"
        meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
        n = {name: len(data) if data is not None else 0 for name, data in t["signals"].items()}
        warn = []
        if not t["audio_file"]:
            warn.append("NO USABLE WAV")
        if meta.get("capture_mode") == "sequential_audio_then_sensors":
            warn.append("SEQUENTIAL PASSES (not time-synchronized)")
        if meta.get("recording_status") not in (None, "complete"):
            warn.append("INCOMPLETE EXPORT")
        if not meta.get("mpu_ready", True):
            warn.append("MPU NOT INITIALIZED")
        d = meta.get("capture_seconds", 0)
        m = meta.get("missed", {})
        for sensor, total in (("audio", d*6000), ("analog", d*500), ("mpu_deadlines", d*200)):
            misses = m.get(sensor, 0)
            if total and misses / total > .05:
                warn.append(f"{sensor} misses {misses/total:.1%}")
        if n["mpu6050"] < 400:
            warn.append("MPU SHORT/EMPTY")
        print(t["label"], path.name, n, "; ".join(warn) or "OK")
    print("\nRecommended: 20-30 separate sessions PER person + 15-20 No Footsteps sessions;")
    print("vary days/surfaces/shoes and test on entirely unseen days/sessions.")


if __name__ == "__main__":
    main()
