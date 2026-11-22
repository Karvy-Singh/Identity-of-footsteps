"""Offline end-to-end mock of the cloud payload, no real ThingSpeak API key."""
import importlib.util
import json
import math
import struct
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path

from footstep_id.thingspeak_transport import (decode_feeds, restore_session,
                                               zip_to_updates, session_to_zip)


class CloudFormatTest(unittest.TestCase):
    def make_session(self, root):
        session = Path(root) / "Harsh" / "session_test"
        session.mkdir(parents=True)
        (session / "metadata.json").write_text(json.dumps({
            "person_id": "Harsh", "recording_status": "complete",
            "audio_usable_for_training": True,
            "capture_mode": "sequential_audio_then_sensors",
        }))
        with wave.open(str(session / "audio.wav"), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(6000)
            data = [int(12000 * math.sin(i / 10)) for i in range(60000)]
            wav.writeframes(struct.pack("<" + "h"*len(data), *data))
        for sensor in ("microphone.csv", "piezo.csv", "mpu6050.csv"):
            (session / sensor).write_text("person_id,time_s,raw\n" +
                    "".join(f"Harsh,{i/500},{i%100}\n" for i in range(5000)))
        return session

    def test_packet_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.make_session(tmp)
            blob = session_to_zip(session)
            sid, updates = zip_to_updates(blob)
            self.assertTrue(1 <= len(updates) <= 900)
            for row in updates:
                for i in range(1, 9):
                    self.assertLessEqual(len(row.get(f"field{i}", "")), 255)
            # Cloud rows may be returned out of order; index markers recover them.
            groups = decode_feeds(list(reversed(updates)))
            out = restore_session(groups[sid], Path(tmp) / "pc_downloaded")
            for fn in ("audio.wav", "microphone.csv", "piezo.csv", "mpu6050.csv", "metadata.json"):
                self.assertEqual((session / fn).read_bytes(), (out / fn).read_bytes())

    def test_incomplete_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.make_session(tmp)
            sid, rows = zip_to_updates(session_to_zip(session))
            if len(rows) <= 1:
                self.skipTest("This test needs >1 packet")
            groups = decode_feeds(rows[:-1])
            with self.assertRaisesRegex(ValueError, "incomplete"):
                restore_session(groups[sid], Path(tmp) / "pc_downloaded")

    def test_arduino_pack_compatible(self):
        # Mimic App Lab's module names without installing actual UNO Q modules.
        with tempfile.TemporaryDirectory() as tmp:
            session = self.make_session(tmp)
            arduino_mod = types.ModuleType("arduino")
            app_mod = types.ModuleType("arduino.app_utils")
            app_mod.App = object
            app_mod.Bridge = object
            sys.modules["arduino"] = arduino_mod
            sys.modules["arduino.app_utils"] = app_mod
            sketch_py = Path(__file__).resolve().parents[2] / "unoq_footstep_thingspeak" / "main.py"
            # Build tests running from standalone PC folder can use board path
            # from a sibling directory; skip if not present.
            if not sketch_py.exists():
                self.skipTest("Arduino companion folder not located")
            spec = importlib.util.spec_from_file_location("test_unoq_recorder", sketch_py)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sid, checksum, rows, nbytes = module.cloud_pack_session(session)
            groups = decode_feeds(rows)
            out = restore_session(groups[sid], Path(tmp) / "download")
            self.assertEqual((session / "audio.wav").read_bytes(), (out / "audio.wav").read_bytes())
            self.assertGreater(nbytes, 0)

if __name__ == "__main__":
    unittest.main()
