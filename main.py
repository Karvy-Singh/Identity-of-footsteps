
from arduino.app_utils import App, Bridge

from pathlib import Path
import csv
import json
import math
import time

# ===================================
# DATASET CONFIGURATION
# ===================================

PERSON_ID = "person_02"
TRIAL_NUMBER = 1

# Set True to record repeated trials
# of the SAME person automatically.
# There will be gaps during download.
AUTO_REPEAT_SAME_PERSON = False

ADC_MAX = 16383.0
ADC_VOLTAGE = 3.3
MISSING = -32768

dataset_root = (
    Path.cwd() / "footstep_dataset" / PERSON_ID
)

dataset_root.mkdir(
    parents=True, exist_ok=True
)

phase = "connect"
record_start = 0.0
capture_seconds = 15
analog_rate = 500
mpu_rate = 200

last_progress = 0.0
connect_start = time.monotonic()

capture_status = None


# ===================================
# BRIDGE COMMUNICATION
# ===================================

def rpc(cmd, index=0, retries=3):
    last_error = None

    for attempt in range(retries):
        try:
            response = Bridge.call(
                "footstep_rpc",
                cmd,
                index,
                timeout=5
            )

            if response is None or len(response) != 25:
                raise ValueError(
                    "Invalid Bridge response"
                )

            return response

        except Exception as e:
            last_error = e
            time.sleep(0.25)

    raise RuntimeError(
        f"Bridge command {cmd} failed: "
        f"{last_error}"
    )


# ===================================
# SAVE MICROPHONE AND PIEZO
# ===================================

def save_analog(folder, total):
    mic_path = folder / "microphone.csv"
    piezo_path = folder / "piezo.csv"

    with (
        mic_path.open("w", newline="") as mf,
        piezo_path.open("w", newline="") as pf
    ):
        mic_writer = csv.writer(mf)
        piezo_writer = csv.writer(pf)

        header = [
            "person_id",
            "trial",
            "sample",
            "time_us",
            "time_s",
            "raw",
            "voltage_v"
        ]

        mic_writer.writerow(header)
        piezo_writer.writerow(header)

        pos = 0

        while pos < total:
            block = rpc(2, pos)
            count = int(block[0])

            if not 1 <= count <= min(6, total-pos):
                raise RuntimeError(
                    f"Invalid analog block at {pos}"
                )

            for i in range(count):
                j = 1 + i * 4

                t_mic = int(block[j])
                mic = int(block[j + 1])

                t_piezo = int(block[j + 2])
                piezo = int(block[j + 3])

                n = pos + i

                mic_v = (
                    "nan" if mic == MISSING
                    else f"{mic * ADC_VOLTAGE / ADC_MAX:.6f}"
                )

                piezo_v = (
                    "nan" if piezo == MISSING
                    else f"{piezo * ADC_VOLTAGE / ADC_MAX:.6f}"
                )

                mic_writer.writerow([
                    PERSON_ID,
                    TRIAL_NUMBER,
                    n,
                    t_mic,
                    f"{t_mic / 1000000.0:.6f}",
                    mic,
                    mic_v
                ])

                piezo_writer.writerow([
                    PERSON_ID,
                    TRIAL_NUMBER,
                    n,
                    t_piezo,
                    f"{t_piezo / 1000000.0:.6f}",
                    piezo,
                    piezo_v
                ])

            pos += count
            time.sleep(0.005)

    print("Saved microphone:", mic_path)
    print("Saved piezo:", piezo_path)


# ===================================
# SAVE MPU6050
# ===================================

def save_mpu(folder, total):
    path = folder / "mpu6050.csv"

    with path.open("w", newline="") as f:
        writer = csv.writer(f)

        writer.writerow([
            "person_id",
            "trial",
            "sample",
            "time_us",
            "time_s",
            "x_raw",
            "y_raw",
            "z_raw",
            "x_g",
            "y_g",
            "z_g",
            "magnitude_g"
        ])

        pos = 0

        while pos < total:
            block = rpc(3, pos)
            count = int(block[0])

            if not 1 <= count <= min(6, total-pos):
                raise RuntimeError(
                    f"Invalid MPU block at {pos}"
                )

            for i in range(count):
                j = 1 + i * 4

                t_us = int(block[j])
                rx = int(block[j + 1])
                ry = int(block[j + 2])
                rz = int(block[j + 3])

                if MISSING in (rx, ry, rz):
                    values = ["nan"] * 4
                else:
                    x = rx / 16384.0
                    y = ry / 16384.0
                    z = rz / 16384.0

                    magnitude = math.sqrt(
                        x*x + y*y + z*z
                    )

                    values = [
                        f"{x:.6f}",
                        f"{y:.6f}",
                        f"{z:.6f}",
                        f"{magnitude:.6f}"
                    ]

                writer.writerow([
                    PERSON_ID,
                    TRIAL_NUMBER,
                    pos + i,
                    t_us,
                    f"{t_us / 1000000.0:.6f}",
                    rx,
                    ry,
                    rz,
                    *values
                ])

            pos += count
            time.sleep(0.005)

    print("Saved MPU6050:", path)


# ===================================
# DOWNLOAD ONE RECORDING
# ===================================

def download_capture(status):
    timestamp = time.strftime(
        "%Y%m%d_%H%M%S"
    )

    folder = dataset_root / (
        f"trial_{TRIAL_NUMBER:03d}_{timestamp}"
    )

    folder.mkdir(parents=True, exist_ok=True)

    analog_count = int(status[1])
    mpu_count = int(status[2])

    print()
    print("CAPTURE FINISHED")
    print("Analog sample pairs:", analog_count)
    print("MPU samples:", mpu_count)

    print("Missed analog slots:", status[3])
    print("Missed MPU slots:", status[4])
    print("MPU read errors:", status[5])
    print("ADC errors:", status[6])
    print("MPU ready:", status[7])

    save_analog(folder, analog_count)
    save_mpu(folder, mpu_count)

    metadata = {
        "person_id": PERSON_ID,
        "trial": TRIAL_NUMBER,
        "capture_seconds": capture_seconds,
        "target_analog_hz": analog_rate,
        "target_mpu_hz": mpu_rate,
        "analog_samples": analog_count,
        "mpu_samples": mpu_count,
        "missed_analog_slots": int(status[3]),
        "missed_mpu_slots": int(status[4]),
        "mpu_read_errors": int(status[5]),
        "adc_errors": int(status[6]),
        "actual_analog_average_hz":
            analog_count / capture_seconds,
        "actual_mpu_average_hz":
            mpu_count / capture_seconds,
        "timestamp_type":
            "microseconds from MCU capture start"
    }

    with (folder / "metadata.json").open("w") as f:
        json.dump(metadata, f, indent=2)

    print()
    print("ALL FILES SAVED")
    print("Folder:", folder)


# ===================================
# MAIN APP LOOP
# ===================================

def loop():
    global phase
    global record_start
    global capture_seconds
    global analog_rate
    global mpu_rate
    global last_progress
    global capture_status
    global TRIAL_NUMBER

    if phase in ("done", "error"):
        time.sleep(1)
        return

    if phase == "connect":
        try:
            status = rpc(0, retries=1)

            capture_seconds = int(status[8])
            analog_rate = int(status[9])
            mpu_rate = int(status[10])

            print("Arduino connected!")
            print("Person:", PERSON_ID)
            print("Trial:", TRIAL_NUMBER)
            print("Duration:", capture_seconds)
            phase = "start"

        except Exception as e:
            if time.monotonic() - connect_start > 30:
                print("Connection failed:", e)
                phase = "error"
            else:
                time.sleep(1)

        return

    if phase == "start":
        try:
            result = rpc(1)

            if int(result[0]) != 1:
                raise RuntimeError(
                    "Capture request rejected"
                )

            print()
            print("RECORDING:", PERSON_ID)
            print("TRIAL:", TRIAL_NUMBER)

            record_start = time.monotonic()
            last_progress = record_start
            phase = "recording"

        except Exception as e:
            print("Start failed:", e)
            phase = "error"

        return

    if phase == "recording":
        now = time.monotonic()
        elapsed = now - record_start

        if elapsed < capture_seconds + 0.5:
            if now - last_progress >= 3:
                print(
                    f"Recording: "
                    f"{min(elapsed, capture_seconds):.1f}s"
                )
                last_progress = now

            time.sleep(0.1)
            return

        phase = "check"

    if phase == "check":
        try:
            status = rpc(0)

            if int(status[0]) != 2:
                time.sleep(0.5)
                return

            capture_status = status
            phase = "download"

        except Exception as e:
            print("Status error:", e)
            time.sleep(1)

        return

    if phase == "download":
        try:
            download_capture(capture_status)

            if AUTO_REPEAT_SAME_PERSON:
                TRIAL_NUMBER += 1
                phase = "start"
            else:
                phase = "done"

        except Exception as e:
            print("Download error:", e)
            print("Retrying download...")
            time.sleep(2)


print("FOOTSTEP ML DATASET LOGGER")
print("Person:", PERSON_ID)
print("Output:", dataset_root)

App.run(user_loop=loop)
