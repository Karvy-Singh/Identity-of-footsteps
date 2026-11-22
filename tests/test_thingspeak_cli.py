import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from footstep_id.thingspeak_cli import main
from footstep_id.thingspeak_transport import zip_to_updates, session_to_zip

class CloudCliTest(unittest.TestCase):
    def test_cli_restores_complete_mock_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/'Harsh'/'session_001';source.mkdir(parents=True)
            (source/'metadata.json').write_text(json.dumps({
                'person_id':'Harsh', 'recording_status':'complete',
                'capture_mode':'sequential_audio_then_sensors',
                'audio_usable_for_training':False}))
            for fn in ('audio.wav','microphone.csv','piezo.csv','mpu6050.csv'):
                (source/fn).write_bytes(b'sample data '+fn.encode())
            sid, updates=zip_to_updates(session_to_zip(source))
            target=root/'restored'
            with patch('footstep_id.thingspeak_cli.fetch_feeds', return_value=updates):
                self.assertEqual(main(['pull','--channel','123','--session-id',sid,
                                       '--dest',str(target)]), 0)
            recreated=target/'Harsh'/f'session_cloud_{sid}'
            self.assertEqual((recreated/'audio.wav').read_bytes(),(source/'audio.wav').read_bytes())

if __name__ == '__main__':
    unittest.main()
