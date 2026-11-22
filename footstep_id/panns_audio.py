"""PANNs CNN14_16k acoustic embeddings, followed by a separately trained identity SVM.

The original AudioSet categories are NOT person identities. We use its 2048-dim
'embedding' output, not its 527 AudioSet label scores, for supervised identities.
"""
from pathlib import Path
from urllib.request import urlretrieve
import sys
import math
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from .config import ROOT

PANN_REPO = ROOT / "vendor" / "audioset_tagging_cnn"
CKPT = ROOT / "checkpoints" / "Cnn14_16k_mAP=0.438.pth"
CKPT_URL = "https://zenodo.org/record/3987831/files/Cnn14_16k_mAP%3D0.438.pth?download=1"


def load_wave(path):
    wave, original_rate = sf.read(str(path), dtype="float32", always_2d=False)
    if wave.ndim == 2:
        wave = wave.mean(axis=1)
    if original_rate != 16000:
        gcd = math.gcd(original_rate, 16000)
        wave = resample_poly(wave, 16000 // gcd, original_rate // gcd)
    wave = np.asarray(wave, dtype=np.float32)
    if len(wave) < 32000:
        raise ValueError(f"At least 2 seconds of audio are required: {path}")
    return wave


def audio_windows(wave):
    """Returns (start_sec, fixed length 2-second audio) every second."""
    for start in range(0, len(wave) - 32000 + 1, 16000):
        yield start / 16000, wave[start:start + 32000]


class PANNsEncoder:
    def __init__(self, download=True):
        try:
            import torch
        except ImportError as exc:
            raise ImportError("Audio encoder requires pip install torch torchlibrosa") from exc
        if not (PANN_REPO / "pytorch" / "models.py").exists():
            raise FileNotFoundError(
                f"Clone https://github.com/qiuqiangkong/audioset_tagging_cnn into {PANN_REPO}")
        sys.path.insert(0, str(PANN_REPO / "pytorch"))
        try:
            from models import Cnn14_16k
        except ImportError as exc:
            raise ImportError("Install torchlibrosa for the official PANNs model") from exc
        if not CKPT.exists():
            if not download:
                raise FileNotFoundError(f"Missing model checkpoint: {CKPT}")
            CKPT.parent.mkdir(parents=True, exist_ok=True)
            temp = CKPT.with_suffix(".partial")
            try:
                print("Downloading pretrained PANNs CNN14_16k (~359 MB)...")
                urlretrieve(CKPT_URL, str(temp))
                if temp.stat().st_size < 100_000_000:
                    raise RuntimeError("Downloaded checkpoint is unusually small")
                temp.replace(CKPT)
            finally:
                if temp.exists():
                    temp.unlink()
        self.torch = torch
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = Cnn14_16k(sample_rate=16000, window_size=512,
                               hop_size=160, mel_bins=64, fmin=50,
                               fmax=8000, classes_num=527)
        ckpt = torch.load(CKPT, map_location="cpu", weights_only=True)
        self.model.load_state_dict(ckpt["model"])
        self.model = self.model.to(self.device).eval()

    def embed(self, wave_2_sec):
        if len(wave_2_sec) != 32000:
            raise ValueError("PANNs model input must be exactly 2 seconds at 16kHz")
        x = self.torch.from_numpy(np.asarray(wave_2_sec, dtype=np.float32).copy())
        x = x[None, :].to(self.device)
        with self.torch.inference_mode():
            result = self.model(x)
        # Used to train our own identity classifier, NOT the AudioSet event labels.
        return result["embedding"][0].detach().cpu().numpy()
