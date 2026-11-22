"""Identical feature engineering for offline CSVs and live UNO Q data."""
import numpy as np
from scipy.signal import find_peaks, welch
from scipy.integrate import trapezoid


def _clean(signal):
    x = np.asarray(signal, dtype=np.float64).reshape(-1)
    if not np.all(np.isfinite(x)):
        valid = np.isfinite(x)
        if valid.sum() < max(10, int(len(x) * 0.95)):
            return None
        x = np.interp(np.arange(len(x)), np.flatnonzero(valid), x[valid])
    return x


def _one_channel(signal, sr):
    x = _clean(signal)
    if x is None or len(x) < 10:
        return None
    # Remove local DC offset; avoid using the sensor's static bias as a person's identity.
    x = x - np.median(x)
    a = np.abs(x)
    rms = np.sqrt(np.mean(x * x))
    mad = np.median(a)
    hist = [
        np.log1p(rms), np.log1p(np.std(x)), np.log1p(mad),
        np.log1p(np.quantile(a, .90)), np.log1p(np.quantile(a, .99)),
        np.log1p(np.max(a)), np.log1p(np.ptp(x)),
        np.mean(a > (np.median(a) + 3 * (mad + 1e-8))),
        np.mean(np.diff(np.signbit(x))),
        np.log1p(np.max(a) / (rms + 1e-8)),
    ]
    prominence = max(2 * mad, .25 * float(np.quantile(a, .95)), 1e-6)
    peaks, _ = find_peaks(a, distance=max(1, int(.12 * sr)), prominence=prominence)
    hist.append(len(peaks) / (len(x) / sr))
    hz, psd = welch(x, fs=sr, nperseg=min(len(x), 256))
    total = float(trapezoid(psd, hz))
    hist.append(float(np.sum(hz * psd) / (np.sum(psd) + 1e-10) / (sr / 2)))
    for lo, hi in [(0.5, 3), (3, 10), (10, 30), (30, 80), (80, sr / 2)]:
        selection = (hz >= lo) & (hz < hi)
        power = float(trapezoid(psd[selection], hz[selection])) if selection.sum() > 1 else 0.
        hist.append(np.log1p(power))
        hist.append(power / (total + 1e-10))
    return np.asarray(hist, dtype=np.float64)


def extract_features(sensor, window):
    if sensor in ("microphone", "piezo"):
        arr = np.asarray(window, dtype=float)
        if arr.ndim != 1:
            raise ValueError(f"{sensor} expects a one-dimensional raw ADC signal")
        # Missing sentinel is negative in a non-negative ADC channel.
        arr[arr == -32768] = np.nan
        return _one_channel(arr, sr=500)
    if sensor == "mpu6050":
        arr = np.asarray(window, dtype=float)
        if arr.ndim != 2 or arr.shape[1] != 3:
            raise ValueError("mpu6050 expects Nx3 acceleration, in units of g")
        arr[arr == -32768] = np.nan
        magnitude = np.linalg.norm(arr, axis=1)
        # These 4 series are all in g; dynamic motion is relative to local gravity.
        outputs = [_one_channel(arr[:, i], 200) for i in range(3)]
        outputs.append(_one_channel(magnitude, 200))
        if any(item is None for item in outputs):
            return None
        return np.concatenate(outputs)
    raise ValueError(f"Unknown sensor: {sensor}")


def signal_windows(sensor, data, *, window_sec=2, step_sec=1):
    sr = 200 if sensor == "mpu6050" else 500
    length = window_sec * sr
    stride = step_sec * sr
    for start in range(0, len(data) - length + 1, stride):
        feats = extract_features(sensor, data[start:start + length])
        if feats is not None:
            yield start / sr, feats
