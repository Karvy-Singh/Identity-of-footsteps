"""Train 3 sensor models and optionally the 4th PANNs audio identity model."""
import argparse
from . import train_sensors, train_audio


def main():
    ap = argparse.ArgumentParser(description="Train independent sensor and audio models")
    ap.add_argument("dataset", help="pulled footstep_dataset folder")
    ap.add_argument("--sensors-only", action="store_true", help="skip PANNs audio embeddings")
    args = ap.parse_args()
    print("Training microphone / piezo / MPU models...")
    train_sensors.train(args.dataset)
    if not args.sensors_only:
        print("Training PANNs embedding + audio SVM (needs 3+ WAV sessions per class)...")
        train_audio.train(args.dataset)
    print("Training complete.")


if __name__ == "__main__":
    main()
