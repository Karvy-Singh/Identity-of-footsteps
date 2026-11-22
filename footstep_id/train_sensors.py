"""Train THREE independent RBF SVMs, with group-held-out validation."""
import argparse
import json
from collections import Counter
from pathlib import Path
import joblib
import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from .config import LABELS, MODELS, REPORTS
from .data_io import SENSORS, iter_trials
from .features import signal_windows


def make_svm():
    return make_pipeline(StandardScaler(), SVC(kernel="rbf", C=10,
                                               gamma="scale", probability=True,
                                               class_weight="balanced", random_state=42))


def train(source):
    trials = list(iter_trials(source))
    rng = np.random.default_rng(42)
    chosen = {}
    # One distinct session per class; never split overlapping windows across sets.
    for label in LABELS:
        pool = [r for r in trials if r["label"] == label]
        if len(pool) < 3:
            raise RuntimeError(f"Need >=3 separate sessions of {label} for training+holdout; have {len(pool)}")
        chosen[label] = pool[int(rng.integers(len(pool)))]["id"]
    heldout_ids = set(chosen.values())
    report = {"sessions_per_class": dict(Counter(t["label"] for t in trials)),
              "held_out_sessions": chosen, "models": {},
              "warning": "Only one session per class held out. Collect more unseen days and surfaces."}
    MODELS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    for sensor in SENSORS:
        xs, ys, groups = [], [], []
        skipped = 0
        for trial in trials:
            data = trial["signals"][sensor]
            length = 400 if sensor == "mpu6050" else 1000
            if data is None or len(data) < length:
                skipped += 1
                continue
            for _, feature in signal_windows(sensor, data):
                xs.append(feature)
                ys.append(trial["label"])
                groups.append(trial["id"])
        if not xs:
            raise RuntimeError(f"No usable windows for {sensor}")
        X = np.stack(xs)
        y = np.asarray(ys)
        groups = np.asarray(groups)
        is_test = np.isin(groups, list(heldout_ids))
        if set(y[~is_test]) != set(LABELS):
            raise RuntimeError(f"Cannot train {sensor}: some classes missing from training windows")
        if not np.any(is_test):
            raise RuntimeError(f"Cannot test {sensor}: no held-out valid windows")
        validator = make_svm().fit(X[~is_test], y[~is_test])
        y_pred = validator.predict(X[is_test])
        probs = validator.predict_proba(X[is_test])
        heldout_groups = groups[is_test]
        heldout_y = y[is_test]
        votes = {}
        for group in sorted(set(heldout_groups)):
            idx = np.flatnonzero(heldout_groups == group)
            top = validator.classes_[int(np.argmax(probs[idx].mean(axis=0)))]
            votes[str(group)] = {"actual": str(heldout_y[idx[0]]),
                                 "predicted": str(top), "windows": len(idx)}
        session_accuracy = np.mean([row["actual"] == row["predicted"] for row in votes.values()])
        report["models"][sensor] = {
            "training_windows": int((~is_test).sum()),
            "held_out_windows": int(is_test.sum()),
            "held_out_window_accuracy": round(float(accuracy_score(y[is_test], y_pred)), 4),
            "held_out_session_accuracy": round(float(session_accuracy), 4),
            "held_out_confusion_matrix": confusion_matrix(y[is_test], y_pred, labels=LABELS).tolist(),
            "held_out_session_predictions": votes, "empty_or_short_trials": skipped}
        model = make_svm().fit(X, y)
        joblib.dump({"model": model, "sensor": sensor, "labels": LABELS,
                     "window_sec": 2, "sample_rate": 200 if sensor == "mpu6050" else 500},
                    MODELS / (sensor + ".joblib"))
        print(f"{sensor}: held-out windows={is_test.sum()} accuracy={accuracy_score(y[is_test],y_pred):.3f} "
              f"session_accuracy={session_accuracy:.3f}", flush=True)
    (REPORTS / "sensor_holdout.json").write_text(json.dumps(report, indent=2))
    print("Sensor models saved in", MODELS)
    return report


def main():
    parser = argparse.ArgumentParser(description="Train sensor models from adb-pulled dataset or original ZIP")
    parser.add_argument("dataset", help="footstep_dataset/ directory or original data(7).zip")
    args = parser.parse_args()
    train(args.dataset)


if __name__ == "__main__":
    main()
