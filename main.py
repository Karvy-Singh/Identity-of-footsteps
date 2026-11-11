
from arduino.app_utils import App, Bridge

from pathlib import Path
import csv
import math
import time

# ===================================
# CONFIGURATION
# ===================================

MIC_RATE = 4000.0
PIEZO_RATE = 1000.0
MPU_RATE = 200.0

ADC_MAX = 16383.0
ADC_VOLTAGE = 3.3

MISSING = -32768

# ===================================
# OUTPUT FOLDER
# ===================================

folder_name = time.strftime(
    "footstep_capture_%Y%m%d_%H%M%S"
)

output_dir = Path.cwd() / folder_name
output_dir.mkdir(parents=True, exist_ok=True)

MIC_FILE = output_dir / "microphone.csv"
PIEZO_FILE = output_dir / "piezo.csv"
MPU_FILE = output_dir / "mpu6050.csv"

# ===================================
# STATE
# ===================================

phase = "connect"

capture_seconds = 2
capture_start = 0.0

last_progress = 0.0
connect_start = time.monotonic()

# ===================================
# BRIDGE COMMUNICATION
# ===================================

def rpc(cmd, index=0, retries=3):

    last_error = None

    for attempt in range(retries):

        try:
            result = Bridge.call(
                "footstep_rpc",
                cmd,
                index,
                timeout=5
            )

            if result is None or len(result) != 41:
                raise ValueError(
                    "Invalid Bridge response"
                )

            return result

        except Exception as e:
            last_error = e

            if attempt + 1 < retries:
                time.sleep(0.25)

    raise RuntimeError(
        f"Bridge command {cmd} failed: {last_error}"
    )

# ===================================
# SAVE ANALOG DATA
# ===================================

def save_analog(cmd, path, total, rate):

    print("Downloading:", path.name)

    with open(path, "w", newline="") as f:

        writer = csv.writer(f)

        writer.writerow([
            "sample",
            "time_s",
            "raw",
            "voltage_v"
        ])

        start = 0

        while start < total:

            block = rpc(cmd, start)
            count = int(block[0])

            if count < 1 or count > min(40, total - start):
                raise RuntimeError(
                    f"Invalid block at {start}"
                )

            for i in range(count):

                raw = int(block[i + 1])
                sample = start + i

                if raw == MISSING:
                    voltage = "nan"
                else:
                    voltage = (
                        f"{raw / ADC_MAX * ADC_VOLTAGE:.6f}"
                    )

                writer.writerow([
                    sample,
                    f"{sample / rate:.6f}",
                    raw,
                    voltage
                ])

            start += count

            time.sleep(0.005)

    print("Saved:", path)

# ===================================
# SAVE MPU6050 DATA
# ===================================

def save_mpu(total):

    print("Downloading MPU6050...")

    with open(MPU_FILE, "w", newline="") as f:

        writer = csv.writer(f)

        writer.writerow([
            "sample",
            "time_s",
            "x_raw",
            "y_raw",
            "z_raw",
            "x_g",
            "y_g",
            "z_g",
            "magnitude_g"
        ])

        start = 0

        while start < total:

            block = rpc(4, start)
            frames = int(block[0])

            if frames < 1 or frames > min(10, total - start):
                raise RuntimeError(
                    f"Invalid MPU block at {start}"
                )

            for i in range(frames):

                base = 1 + 3 * i

                rx = int(block[base])
                ry = int(block[base + 1])
                rz = int(block[base + 2])

                sample = start + i
                time_s = sample / MPU_RATE

                if (
                    rx == MISSING or
                    ry == MISSING or
                    rz == MISSING
                ):

                    writer.writerow([
                        sample,
                        f"{time_s:.6f}",
                        rx, ry, rz,
                        "nan", "nan", "nan", "nan"
                    ])

                else:

                    x = rx / 16384.0
                    y = ry / 16384.0
                    z = rz / 16384.0

                    magnitude = math.sqrt(
                        x*x + y*y + z*z
                    )

                    writer.writerow([
                        sample,
                        f"{time_s:.6f}",
                        rx, ry, rz,
                        f"{x:.6f}",
                        f"{y:.6f}",
                        f"{z:.6f}",
                        f"{magnitude:.6f}"
                    ])

            start += frames
            time.sleep(0.005)

    print("Saved:", MPU_FILE)

# ===================================
# DOWNLOAD ALL SENSOR DATA
# ===================================

def download_all(status):

    mic_count = int(status[1])
    piezo_count = int(status[2])
    mpu_count = int(status[3])

    print()
    print("============================")
    print("CAPTURE COMPLETE")
    print("============================")

    print("Microphone slots:", mic_count)
    print("Piezo slots:", piezo_count)
    print("MPU6050 slots:", mpu_count)

    print()
    print("Missed microphone slots:", status[4])
    print("Missed piezo slots:", status[5])
    print("Missed MPU slots:", status[6])
    print("MPU read errors:", status[7])
    print("MPU ready:", status[8])

    print()
    print("Starting CSV download...")

    save_analog(
        2, MIC_FILE, mic_count, MIC_RATE
    )

    save_analog(
        3, PIEZO_FILE, piezo_count, PIEZO_RATE
    )

    save_mpu(mpu_count)

    print()
    print("============================")
    print("ALL CSV FILES SAVED!")
    print("============================")
    print("Folder:", output_dir)

# ===================================
# MAIN APP LOOP
# ===================================

def loop():

    global phase
    global capture_seconds
    global capture_start
    global last_progress

    if phase == "done" or phase == "error":
        time.sleep(1)
        return

    # CONNECT
    if phase == "connect":

        try:
            status = rpc(0, retries=1)

            capture_seconds = int(status[9])

            print("Bridge connected!")
            print("Capture duration:", capture_seconds)
            print("Output folder:", output_dir)

            phase = "start"

        except Exception as e:

            if time.monotonic() - connect_start > 30:
                print("MCU Bridge unavailable:", e)
                print("Check the App launch / Sketch console.")
                phase = "error"
            else:
                print("Waiting for MCU:", e)
                time.sleep(1)

        return

    # START CAPTURE
    if phase == "start":

        try:
            response = rpc(1)

            if int(response[0]) != 1:
                raise RuntimeError(
                    "Capture request rejected"
                )

            print()
            print("RECORDING STARTED!")

            capture_start = time.monotonic()
            last_progress = capture_start

            phase = "recording"

        except Exception as e:
            print("Start error:", e)
            phase = "error"

        return

    # RECORD WITHOUT BRIDGE CALLS
    if phase == "recording":

        now = time.monotonic()
        elapsed = now - capture_start

        if elapsed < capture_seconds + 0.5:

            if now - last_progress >= 0.5:
                print(
                    f"Recording: "
                    f"{min(elapsed, capture_seconds):.1f}"
                    f"/{capture_seconds} seconds"
                )
                last_progress = now

            time.sleep(0.1)
            return

        phase = "check"

    # CHECK COMPLETION
    if phase == "check":

        try:
            status = rpc(0)

            if int(status[0]) != 2:

                print("Waiting for capture to finish...")
                time.sleep(0.5)
                return

            phase = "download"

        except Exception as e:
            print("Status error:", e)
            phase = "error"
            return

    # DOWNLOAD DATA
    if phase == "download":

        try:
            download_all(status)
            phase = "done"

        except Exception as e:
            print("Download error:", e)
            phase = "error"


print("============================")
print("FOOTSTEP SENSOR LOGGER")
print("============================")
print("Microphone: 4000 Hz")
print("Piezo: 1000 Hz")
print("MPU6050: 200 Hz")
print("Waiting for Arduino UNO Q...")

App.run(user_loop=loop)
