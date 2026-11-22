"""Classify ONE synchronized recording; 2-second windows, stride 1s, vote last 5."""
import argparse
import json
from pathlib import Path
import joblib
import numpy as np
from .config import LABELS, MODELS
from .data_io import load_trial_folder, SENSORS
from .features import extract_features, signal_windows
from .fusion import fuse, RollingVote


def load_classifiers():
    result = {}
    for name in (*SENSORS, "audio"):
        path = MODELS / (name + ".joblib")
        if path.exists():
            result[name] = joblib.load(path)["model"]
    return result


def scores_from_model(model, features):
    p = model.predict_proba(np.asarray(features).reshape(1, -1))[0]
    return {str(label): float(prob) for label, prob in zip(model.classes_, p)}


def predict_session(trial_dir, audio_file=None, audio_offset_sec=0.0):
    folder = Path(trial_dir)
    models = load_classifiers()
    signals = load_trial_folder(folder)
    if audio_file is None:
        candidate = folder / "audio.wav"
        audio_file = str(candidate) if candidate.exists() else None
    wave, encoder = None, None
    if audio_file is not None and "audio" in models:
        from .panns_audio import PANNsEncoder, load_wave
        wave = load_wave(audio_file)
        encoder = PANNsEncoder()
    elif audio_file is not None:
        print("WARNING: WAV found but audio.joblib is not trained, using 3 sensors only.")
    lengths = [len(signals[s]) / (200 if s == "mpu6050" else 500)
               for s in SENSORS if signals[s] is not None]
    if not lengths:
        raise ValueError("No usable sensor CSVs")
    duration = max(lengths)
    smoother = RollingVote()
    outputs = []
    for second in range(max(0, int(duration) - 1)):
        scores = {}
        for sensor in SENSORS:
            if sensor not in models or signals[sensor] is None:
                continue
            rate = 200 if sensor == "mpu6050" else 500
            start, end = second * rate, (second + 2) * rate
            if len(signals[sensor]) < end:
                continue
            feat = extract_features(sensor, signals[sensor][start:end])
            if feat is not None:
                scores[sensor] = scores_from_model(models[sensor], feat)
        if wave is not None:
            begin = round((second - audio_offset_sec) * 16000)
            if begin >= 0 and begin + 32000 <= len(wave):
                emb = encoder.embed(wave[begin:begin+32000])
                scores["audio"] = scores_from_model(models["audio"], emb)
        combined = fuse(scores)
        if combined is None:
            continue
        combined.update({"start_sec": second, "end_sec": second+2,
                         "smoothed_label": smoother.update(combined),
                         "individual_predictions": {sensor: max(values, key=values.get)
                                                    for sensor, values in scores.items()},
                         "individual_scores": scores})
        outputs.append(combined)
    return outputs


def session_summary(rows):
    if not rows:
        return {"label": "No prediction", "windows": 0}
    # Aggregate all fused window posteriors to score the complete recording.
    p = {lab: float(np.mean([row["scores"][lab] for row in rows])) for lab in LABELS}
    return {"label": max(p, key=p.get), "mean_scores": p, "windows": len(rows),
            "final_rolling_vote": rows[-1]["smoothed_label"],
            "models_used": sorted(set(name for row in rows for name in row["used_models"]))}


def predict_sequential_session(trial_dir, audio_file=None):
    """Session-level late fusion of independent audio and sensor walking passes.

    NO window-by-window 4-way fusion here: ordinal timestamps in the WAV and
    sensor CSVs are different real walking passes, not synchronized steps.
    """
    trial_dir = Path(trial_dir)
    models = load_classifiers()
    signals = load_trial_folder(trial_dir)
    summaries = {}
    for sensor in SENSORS:
        if sensor not in models or signals[sensor] is None:
            continue
        scores = [scores_from_model(models[sensor], feat)
                  for _, feat in signal_windows(sensor, signals[sensor])]
        if not scores:
            continue
        averaged = {label: float(np.mean([p.get(label, 0.) for p in scores]))
                    for label in LABELS}
        votes = RollingVote()
        last_vote = None
        for window in scores:
            last_vote = votes.update({"label": max(window, key=window.get),
                                      "scores": window})
        summaries[sensor] = {"scores": averaged, "n_windows": len(scores),
                             "last_5_vote": last_vote}

    metadata_path = trial_dir / "metadata.json"
    meta = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    usable = meta.get("audio_usable_for_training") is not False
    if audio_file is None:
        audio_file = str(trial_dir / "audio.wav") if (trial_dir / "audio.wav").exists() else None
    if audio_file and usable and "audio" in models:
        from .panns_audio import PANNsEncoder, load_wave, audio_windows
        wave = load_wave(audio_file)
        encoder = PANNsEncoder()
        scores = [scores_from_model(models["audio"], encoder.embed(clip))
                  for _, clip in audio_windows(wave)]
        if scores:
            averaged = {label: float(np.mean([p.get(label, 0.) for p in scores]))
                        for label in LABELS}
            votes = RollingVote()
            last_vote = None
            for window in scores:
                last_vote = votes.update({"label": max(window, key=window.get),
                                          "scores": window})
            summaries["audio"] = {"scores": averaged, "n_windows": len(scores),
                                  "last_5_vote": last_vote}
    elif audio_file and not usable:
        print("WARNING: WAV skipped due to audio dropout rate >=5%")
    elif audio_file and "audio" not in models:
        print("WARNING: audio identity model not yet trained; using CSVs only.")

    fused = fuse({sensor: entry["scores"] for sensor, entry in summaries.items()})
    if fused is None:
        raise RuntimeError("No usable model windows in this session")
    return {"capture_mode": "sequential_audio_then_sensors",
            "warning": "Model scores are fused at session level: audio and CSVs were not synchronous.",
            "label": fused["label"], "score": fused["score"],
            "scores": fused["scores"], "models_used": fused["used_models"],
            "per_sensor": summaries}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session", help="one person/session_YYYYMMDD_HHMMSS folder")
    ap.add_argument("--audio", help="override audio.wav path; auto-detected otherwise")
    ap.add_argument("--audio-offset-sec", type=float, default=0.0)
    ap.add_argument("--json-output")
    args = ap.parse_args()
    meta_path = Path(args.session) / "metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    if meta.get("capture_mode") == "sequential_audio_then_sensors":
        summary = predict_sequential_session(args.session, args.audio)
        for name, info in summary["per_sensor"].items():
            label = max(info["scores"], key=info["scores"].get)
            print(f'{name:11s} label={label:13s} windows={info["n_windows"]:2d} '
                  f'last_5_vote={info["last_5_vote"]}')
        print("\nSEQUENTIAL SESSION SUMMARY:", json.dumps(summary, indent=2))
        if args.json_output:
            Path(args.json_output).write_text(json.dumps(summary, indent=2))
        return

    predictions = predict_session(args.session, args.audio, args.audio_offset_sec)
    for row in predictions:
        print(f'{row["start_sec"]:2d}-{row["end_sec"]:2d}s '
              f'raw={row["label"]:13s} vote={row["smoothed_label"]:13s} '
              f'score={row["score"]:.3f} models={",".join(row["used_models"])}')
    summary = session_summary(predictions)
    print("\nSESSION SUMMARY:", json.dumps(summary, indent=2))
    if args.json_output:
        Path(args.json_output).write_text(json.dumps({"summary": summary,
                                                       "windows": predictions}, indent=2))


if __name__ == "__main__":
    main()
