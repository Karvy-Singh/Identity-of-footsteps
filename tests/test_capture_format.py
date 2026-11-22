"""Test that the generated UNO Q session format can be read by PC code."""
import csv
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
import types
import unittest
import wave
import numpy as np
from footstep_id.data_io import iter_folder_trials, load_trial_folder
from footstep_id.features import extract_features

PROJECT = Path(__file__).resolve().parents[1]
RECORDER = PROJECT.parent / "unoq_footstep_recorder" / "python" / "main.py"


class TestUnoFormat(unittest.TestCase):
    def test_pc_can_read_generated_recorder_csvs(self):
        with tempfile.TemporaryDirectory() as temp:
            session = Path(temp) / "Harsh" / "session_test"
            session.mkdir(parents=True)
            for name in ("microphone", "piezo"):
                with (session / f"{name}.csv").open("w", newline="") as out:
                    w = csv.writer(out)
                    w.writerow(["person_id", "trial", "sample", "time_us", "time_s", "raw", "voltage_v"])
                    for i in range(1000):
                        w.writerow(["Harsh", 1, i, i*2000, i/500, 7300 if name == "microphone" else 50, 1])
            with (session / "mpu6050.csv").open("w", newline="") as out:
                w = csv.writer(out)
                w.writerow(["person_id", "trial", "sample", "time_us", "time_s", "x_raw", "y_raw", "z_raw", "x_g", "y_g", "z_g", "magnitude_g"])
                for i in range(400):
                    w.writerow(["Harsh", 1, i, i*5000, i/200, 0, 0, 16384, 0, 0, 1, 1])
            arr = load_trial_folder(session)
            self.assertEqual(arr["microphone"].shape, (1000,))
            self.assertEqual(arr["mpu6050"].shape, (400, 3))
            self.assertEqual(len(list(iter_folder_trials(temp))), 1)
            self.assertEqual(extract_features("piezo", arr["piezo"]).shape[0], 22)

    def test_recording_audio_wav_makes_6khz_pcm(self):
        if not RECORDER.exists():
            self.skipTest("Recorder sources not at project sibling")
        arduino = types.ModuleType("arduino")
        utils = types.ModuleType("arduino.app_utils")
        utils.App = type("App", (), {"run": lambda **kwargs: None})
        utils.Bridge = object()
        sys.modules["arduino"] = arduino
        sys.modules["arduino.app_utils"] = utils
        spec = importlib.util.spec_from_file_location("uno_recorder", RECORDER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        audio = [7300 + int(50 * math.sin(2 * math.pi * i / 80)) for i in range(12000)]
        audio[100] = -32768
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "audio.wav"
            stats = module.write_mic_wav(path, audio)
            self.assertEqual(stats["wav_interpolated_gaps"], 1)
            with wave.open(str(path)) as obj:
                self.assertEqual(obj.getframerate(), 6000)
                self.assertEqual(obj.getnchannels(), 1)
                self.assertEqual(obj.getnframes(), 12000)
                self.assertEqual(obj.getsampwidth(), 2)


if __name__ == "__main__":
    unittest.main()
