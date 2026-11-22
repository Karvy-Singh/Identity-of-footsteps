"""Smoke tests run with: python -m unittest discover -s tests -v"""
import unittest
import numpy as np
from footstep_id.features import extract_features, signal_windows
from footstep_id.fusion import RollingVote, fuse
from footstep_id.live_bridge import BridgeCollector
from footstep_id.config import LABELS

class SmokeTests(unittest.TestCase):
    def test_feature_shapes(self):
        mic = extract_features('microphone', np.random.default_rng(42).normal(size=1000))
        piezo = extract_features('piezo', np.zeros(1000))
        mpu = extract_features('mpu6050', np.ones((400, 3)))
        self.assertEqual(mic.shape, piezo.shape)
        self.assertEqual(mpu.shape[0], 4 * mic.shape[0])
        self.assertTrue(np.all(np.isfinite(mpu)))

    def test_2sec_windows_every_1sec(self):
        self.assertEqual(len(list(signal_windows('microphone', np.arange(7500)))), 14)
        self.assertEqual(len(list(signal_windows('mpu6050', np.ones((3000,3))))), 14)

    def test_missing_samples_skipped(self):
        mic = np.ones(1000)
        mic[:100] = -32768
        self.assertIsNone(extract_features('microphone', mic))

    def test_fusion_and_voting(self):
        scores = {name: .02 for name in LABELS}
        scores['Karvy'] = .94
        fused = fuse({'microphone': scores, 'mpu6050': scores})
        self.assertEqual(fused['label'], 'Karvy')
        self.assertEqual(RollingVote().update(fused), 'Karvy')

    def test_mock_bridge_rpc_data(self):
        class FakeBridge:
            def call(self, method, cmd, start, timeout=5):
                if method != "footstep_live_rpc":
                    raise AssertionError(method)
                if cmd == 0:
                    status = [0] * 41
                    status[0], status[1], status[2] = 2026, 1000, 400
                    status[7], status[8] = 500, 200
                    return status
                out = [0] * 41
                produced = 1000 if cmd == 2 else 400
                n = min(40 if cmd == 2 else 13, max(0, produced - start))
                out[0] = n
                for i in range(n):
                    if cmd == 2:
                        # raw microphone=7200, piezo=60, encoded in one 32-bit int
                        out[i + 1] = (7200 << 16) | 60
                    else:
                        out[1 + 3 * i:1 + 3 * i + 3] = [0, 0, 16384]
                return out
        collector = BridgeCollector(FakeBridge())
        for _ in range(3):
            collector.catch_up()
        self.assertTrue(collector.ready())
        self.assertEqual(len(collector.window("microphone", 2)), 1000)
        self.assertEqual(len(collector.window("mpu6050", 2)), 400)
        self.assertTrue(np.allclose(collector.window("mpu6050", 2)[0], [0, 0, 1]))

    def test_bridge_signed_packing(self):
        self.assertEqual(BridgeCollector.unpack_signed_16(0xFFFF), -1)
        self.assertEqual(BridgeCollector.unpack_signed_16(0x8000), -32768)

if __name__ == '__main__':
    unittest.main()
