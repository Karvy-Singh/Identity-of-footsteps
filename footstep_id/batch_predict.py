"""Optional: classify every collected session, writing a JSON summary."""
import argparse
import json
from pathlib import Path
from .data_io import iter_folder_trials
from .predict import predict_session, session_summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--json-output", default="batch_predictions.json")
    args = ap.parse_args()
    out = []
    for trial in iter_folder_trials(args.dataset):
        predictions = predict_session(trial["id"])
        summary = session_summary(predictions)
        out.append({"session": trial["id"], "actual": trial["label"], **summary})
        print(trial["label"], Path(trial["id"]).name, "->", summary["label"])
    Path(args.json_output).write_text(json.dumps(out, indent=2))
    print("Wrote", args.json_output)


if __name__ == "__main__":
    main()
