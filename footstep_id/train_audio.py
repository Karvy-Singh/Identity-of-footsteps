"""Fourth PERSON-IDENTITY SVM using PANNs CNN14_16k embeddings from matched WAVs."""
import argparse
import json
from collections import defaultdict
import numpy as np
import joblib
from sklearn.metrics import accuracy_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler, Normalizer
from sklearn.svm import SVC
from .config import LABELS, MODELS, REPORTS
from .data_io import iter_folder_trials
from .panns_audio import PANNsEncoder, audio_windows, load_wave


def make_model():
    return make_pipeline(Normalizer(), StandardScaler(), SVC(kernel="rbf", C=10,
                         gamma="scale", probability=True,
                         class_weight="balanced", random_state=42))


def train(root):
    trials = list(iter_folder_trials(root))
    audio_trials = defaultdict(list)
    for trial in trials:
        if trial["audio_file"]:
            audio_trials[trial["label"]].append(trial)
    for label in LABELS:
        if len(audio_trials[label]) < 3:
            raise RuntimeError(
                f"Need >=3 labeled WAV sessions for {label} (recommend 20+); "
                f"found {len(audio_trials[label])}. No trained audio identity model yet.")
    # Choose one complete session per class as holdout (stable per class).
    rng = np.random.default_rng(42)
    heldout = {label: audio_trials[label][int(rng.integers(len(audio_trials[label])))]["id"]
               for label in LABELS}
    encoder = PANNsEncoder()
    xs, ys, ids = [], [], []
    for label in LABELS:
        for trial in audio_trials[label]:
            wav = load_wave(trial["audio_file"])
            for _, clip in audio_windows(wav):
                xs.append(encoder.embed(clip))
                ys.append(label)
                ids.append(trial["id"])
            print(f"Embedded {trial['audio_file']}", flush=True)
    X, y, groups = np.stack(xs), np.asarray(ys), np.asarray(ids)
    test_mask = np.isin(groups, list(heldout.values()))
    if set(y[~test_mask]) != set(LABELS):
        raise RuntimeError("Some classes missing from audio training set")
    model = make_model().fit(X[~test_mask], y[~test_mask])
    score = float(accuracy_score(y[test_mask], model.predict(X[test_mask])))
    REPORTS.mkdir(parents=True, exist_ok=True)
    report = {"audio_holdout_window_accuracy": score, "held_out_sessions": heldout,
              "n_sessions": {lab: len(audio_trials[lab]) for lab in LABELS},
              "caveat": "Session-held-out but small dataset; audio 6k ADC limits bandwidth."}
    (REPORTS / "audio_holdout.json").write_text(json.dumps(report, indent=2))
    final = make_model().fit(X, y)
    MODELS.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": final, "sensor": "audio", "labels": LABELS,
                 "window_sec": 2, "sample_rate": 16000,
                 "embedding": "PANNs_CNN14_16k"}, MODELS / "audio.joblib")
    print(f"Audio model saved. Held-out window accuracy: {score:.3f}", flush=True)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="Root directory e.g. footstep_dataset")
    args = ap.parse_args()
    train(args.dataset)


if __name__ == "__main__":
    main()
