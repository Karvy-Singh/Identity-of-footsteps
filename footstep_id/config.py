from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "artifacts" / "models"
REPORTS = ROOT / "artifacts" / "reports"
LABELS = ["Harsh", "Karvy", "Rudra", "No Footsteps"]
RATES = {"microphone": 500, "piezo": 500, "mpu6050": 200, "audio": 16000}
WINDOW_SEC = 2
STEP_SEC = 1
SMOOTHING_SIZE = 5
MODEL_WEIGHTS = {"microphone": 1.0, "piezo": 1.0, "mpu6050": 1.0, "audio": 0.5}
