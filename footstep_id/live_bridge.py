"""Read the user's footstep_live_rpc from UNO Q and run three sensor SVMs live.

The FOURTH model needs a separate, synchronized acoustic-audio input stream.
Do not substitute the 500-Hz ADC microphone channel for 16-kHz WAV audio.
"""
import argparse
import time
from collections import defaultdict

import numpy as np
from .config import LABELS
from .features import extract_features
from .fusion import RollingVote, fuse
from .predict import load_classifiers, scores_from_model


class BridgeCollector:
    def __init__(self, bridge):
        self.bridge = bridge
        status = bridge.call("footstep_live_rpc", 0, 0, timeout=5)
        if int(status[0]) != 2026:
            raise RuntimeError(f"Unexpected firmware protocol marker {status[0]}")
        if int(status[7]) != 500 or int(status[8]) != 200:
            raise RuntimeError("Expected 500-Hz analog and 200-Hz MPU rates")
        self.seq_a = max(0, int(status[1]) - 1000)
        self.seq_m = max(0, int(status[2]) - 400)
        self.buffers = {s: {} for s in ("microphone", "piezo", "mpu6050")}
        self.next_end_sec = max(2, int(min(self.seq_a / 500, self.seq_m / 200)) + 2)
        self.warned = False

    @staticmethod
    def unpack_signed_16(value):
        value &= 0xFFFF
        return value - 65536 if value >= 32768 else value

    def pull_analog(self, max_calls=20):
        for _ in range(max_calls):
            response = self.bridge.call("footstep_live_rpc", 2, self.seq_a, timeout=4)
            count = int(response[0])
            if count == -2:
                self.seq_a = int(response[1])
                self.buffers["microphone"].clear()
                self.buffers["piezo"].clear()
                print("Analog data overrun; resynchronizing at", self.seq_a)
                continue
            if count <= 0:
                break
            for packed in response[1:1 + count]:
                packed = int(packed) & 0xFFFFFFFF
                mic = self.unpack_signed_16(packed >> 16)
                piezo = self.unpack_signed_16(packed)
                self.buffers["microphone"][self.seq_a] = np.nan if mic == -32768 else mic
                self.buffers["piezo"][self.seq_a] = np.nan if piezo == -32768 else piezo
                self.seq_a += 1
            if count < 40:
                break

    def pull_mpu(self, max_calls=20):
        for _ in range(max_calls):
            response = self.bridge.call("footstep_live_rpc", 3, self.seq_m, timeout=4)
            count = int(response[0])
            if count == -2:
                self.seq_m = int(response[1])
                self.buffers["mpu6050"].clear()
                print("MPU data overrun; resynchronizing at", self.seq_m)
                continue
            if count <= 0:
                break
            for i in range(count):
                xyz_raw = np.asarray(response[1 + i*3:4 + i*3], dtype=np.float64)
                xyz_raw[xyz_raw == -32768] = np.nan
                self.buffers["mpu6050"][self.seq_m] = xyz_raw / 16384.
                self.seq_m += 1
            if count < 13:
                break

    def prune(self):
        for sensor, rate in [("microphone", 500), ("piezo", 500), ("mpu6050", 200)]:
            newest = self.seq_m if sensor == "mpu6050" else self.seq_a
            cutoff = newest - 8 * rate
            self.buffers[sensor] = {k: v for k, v in self.buffers[sensor].items() if k >= cutoff}

    def window(self, sensor, end_sec):
        rate = 200 if sensor == "mpu6050" else 500
        begin = (end_sec - 2) * rate
        finish = end_sec * rate
        if begin < 0:
            return None
        buf = self.buffers[sensor]
        if sensor == "mpu6050":
            return np.asarray([buf.get(i, [np.nan, np.nan, np.nan]) for i in range(begin, finish)],
                              dtype=float)
        return np.asarray([buf.get(i, np.nan) for i in range(begin, finish)], dtype=float)

    def ready(self):
        return self.seq_a >= self.next_end_sec * 500 and self.seq_m >= self.next_end_sec * 200

    def catch_up(self):
        self.pull_analog()
        self.pull_mpu()
        self.prune()
        # Detect large backlog due to inference being slower than the ring duration.
        max_completed = int(min(self.seq_a / 500, self.seq_m / 200))
        if self.next_end_sec < max_completed - 6:
            self.next_end_sec = max_completed - 2
            print("Inference fell behind: dropped stale prediction windows")


def run():
    try:
        from arduino.router_bridge import Bridge
    except ImportError as exc:
        raise ImportError("On UNO Q Linux: pip install arduino-router-bridge") from exc
    models = {sensor: model for sensor, model in load_classifiers().items()
              if sensor in ("microphone", "piezo", "mpu6050")}
    if len(models) < 3:
        raise RuntimeError("Train all three sensor models first: python -m footstep_id.train_sensors data.zip")
    vote = RollingVote()
    with Bridge() as bridge:
        print("Connected to UNO Q; reading footstep_live_rpc")
        collector = BridgeCollector(bridge)
        while True:
            collector.catch_up()
            while collector.ready():
                predictions = {}
                for sensor, model in models.items():
                    window = collector.window(sensor, collector.next_end_sec)
                    features = extract_features(sensor, window)
                    if features is not None:
                        predictions[sensor] = scores_from_model(model, features)
                combined = fuse(predictions)
                if combined is not None:
                    label = vote.update(combined)
                    print(f"{collector.next_end_sec - 2}-{collector.next_end_sec}s "
                          f"raw={combined['label']:13s} smoothed={label:13s} "
                          f"score={combined['score']:.3f} "
                          f"sensors={','.join(combined['used_models'])}", flush=True)
                collector.next_end_sec += 1
            time.sleep(.03)


def main():
    try:
        run()
    except KeyboardInterrupt:
        print("Stopped")


if __name__ == "__main__":
    main()
