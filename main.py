"""UNO Q App Lab: sequential 10s audio + 10s numeric sensors (protocol 2028).

Container:  /app/data/footstep_dataset/<PERSON>/<session>/
Host board: /home/arduino/ArduinoApps/lord/data/footstep_dataset/<PERSON>/<session>/
Change APP_NAME in printed ADB instructions if your App Lab app is not 'lord'.

The phases are NOT simultaneous. Do not interpret matching time_s values as the
same footsteps: each file's 0..10 s timeline starts at its OWN acquisition.
"""
from arduino.app_utils import App, Bridge

import csv
import base64
import hashlib
import io
import urllib.error
import urllib.request
import zipfile
import json
import math
import struct
import time
import os
import wave
from datetime import datetime
from pathlib import Path
from statistics import median

# ============ EDIT THESE SETTINGS ============
PERSON = "Harsh"              # Harsh, Karvy, Rudra, or No Footsteps
CAPTURE_SECONDS = 10           # 2 through 10 seconds PER phase
START_DELAY_SECONDS = 3        # 3-second countdown before each phase
APP_NAME = "lord"             # Your Arduino App Lab project slug
DATA_ROOT = Path("/app/data/footstep_dataset")
# Find these on ThingSpeak -> My Channels -> your PRIVATE channel -> API Keys.
# Set these two values before running. Do not share your write key.
THINGSPEAK_CHANNEL_ID = 0              # e.g. 1234567
THINGSPEAK_WRITE_KEY = ""              # e.g. "YOUR_WRITE_API_KEY"
UPLOAD_ENABLED = True
UPLOAD_ONLY = False                     # True: retry locally saved sessions without recording

# =============================================

LABELS = {"Harsh", "Karvy", "Rudra", "No Footsteps"}
PROTOCOL = 2028
MISSING = -32768
ADC_MAX = 16383
ADC_VOLTAGE = 3.3
AUDIO_RATE = 6000
ANALOG_RATE = 500
MPU_RATE = 200
MAX_MISSING_RATE = 0.05
already_recorded = False
# Each ThingSpeak entry has eight string fields (255 chars max). We reserve
# field8 for a manifest marker and use the other seven to hold ZIP/base64.
CLOUD_FILE_NAMES = ("audio.wav", "microphone.csv", "piezo.csv",
                    "mpu6050.csv", "metadata.json")
CLOUD_PART_CHARS = 240
CLOUD_FIELDS_PER_ENTRY = 7
CLOUD_MAX_ENTRIES = 900  # <=960 free-account ThingSpeak bulk limit
CLOUD_STATE_FILE = Path("/app/data/thingspeak_upload_state.json")



def signed16(value):
    value = int(value) & 0xFFFF
    return value - 65536 if value >= 32768 else value


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def read_chunks(cmd, expected, max_per_chunk):
    samples = []
    next_index = 0
    attempts = 0
    while next_index < expected:
        try:
            result = list(Bridge.call("footstep_capture_read", cmd, next_index))
            if not result:
                raise RuntimeError("empty RPC response")
            count = int(result[0])
            if count <= 0 or count > max_per_chunk:
                raise RuntimeError(f"unexpected RPC response cmd={cmd}, offset={next_index}: {count}")
            required = count * (3 if cmd == 3 else 1) + 1
            if len(result) < required:
                raise RuntimeError(f"truncated RPC response len={len(result)} need={required}")
            if cmd == 1:
                new = [signed16(v) for v in result[1:count + 1]]
            elif cmd == 2:
                new = [(signed16(int(v) >> 16), signed16(v))
                       for v in result[1:count + 1]]
            else:
                new = [(signed16(result[1 + 3*i]),
                        signed16(result[2 + 3*i]),
                        signed16(result[3 + 3*i])) for i in range(count)]
            samples.extend(new)
            next_index += count
            attempts = 0
            if (next_index // 5000) != ((next_index - count) // 5000) or next_index == expected:
                print(f"  Download channel {cmd}: {next_index}/{expected}", flush=True)
        except Exception as exc:
            attempts += 1
            if attempts >= 5:
                raise RuntimeError(f"RPC download failed at channel={cmd}, index={next_index}") from exc
            print("  RPC retry:", repr(exc), flush=True)
            time.sleep(0.5)
    return samples


def write_adc_csv(path, person, values):
    with path.open("w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["person_id", "trial", "sample", "time_us", "time_s", "raw", "voltage_v"])
        for i, raw in enumerate(values):
            w.writerow([person, 1, i, i * 2000, f"{i / ANALOG_RATE:.6f}", raw,
                        "" if raw == MISSING else f"{raw * ADC_VOLTAGE / ADC_MAX:.6f}"])


def write_mpu_csv(path, person, values):
    with path.open("w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["person_id", "trial", "sample", "time_us", "time_s",
                    "x_raw", "y_raw", "z_raw", "x_g", "y_g", "z_g", "magnitude_g"])
        for i, (x, y, z) in enumerate(values):
            if MISSING in (x, y, z):
                extra = ["", "", "", ""]
            else:
                gx, gy, gz = x / 16384., y / 16384., z / 16384.
                extra = [f"{gx:.6f}", f"{gy:.6f}", f"{gz:.6f}",
                         f"{math.sqrt(gx*gx + gy*gy + gz*gz):.6f}"]
            w.writerow([person, 1, i, i*5000, f"{i / MPU_RATE:.6f}",
                        x, y, z, *extra])


def fill_missing_audio(raw):
    points = [None if x == MISSING else float(x) for x in raw]
    indices = [i for i, x in enumerate(points) if x is not None]
    if not indices:
        raise RuntimeError("No valid mic samples. Cannot write meaningful WAV.")
    first = indices[0]
    for i in range(first):
        points[i] = points[first]
    prev = first
    for i in indices[1:]:
        if i > prev + 1:
            a, b = points[prev], points[i]
            step = (b-a)/(i-prev)
            for k in range(prev+1, i):
                points[k] = a + (k-prev)*step
        prev = i
    for k in range(prev+1, len(points)):
        points[k] = points[prev]
    return points


def write_wav(path, raw):
    # Gap interpolation makes a playable diagnostic file but it does NOT recover
    # the original waveform. See audio_usable_for_training in metadata.json.
    data = fill_missing_audio(raw)
    bias = median(data)
    pcm = []
    clipped = 0
    for value in data:
        signed = round((value-bias) * 4.)
        if signed < -32768 or signed > 32767:
            clipped += 1
        pcm.append(max(-32768, min(32767, signed)))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(AUDIO_RATE)
        wav.writeframes(struct.pack("<" + "h"*len(pcm), *pcm))
    return {"wav_pcm_gain": 4.0, "audio_adc_baseline": bias,
            "wav_clipped_samples": clipped,
            "wav_interpolated_gaps": raw.count(MISSING)}


def status():
    result = list(Bridge.call("footstep_capture_status"))
    if not result or int(result[0]) != PROTOCOL:
        raise RuntimeError("Sketch/protocol mismatch. Flash the supplied sequential sketch.ino (2028).")
    return result


def capture_phase(label, signed_seconds):
    for remaining in range(START_DELAY_SECONDS, 0, -1):
        print(f"{label} starts in {remaining}...", flush=True)
        time.sleep(1)
    rc = int(Bridge.call("footstep_capture_start", signed_seconds))
    if rc:
        raise RuntimeError(f"MCU refused phase {label}: {rc}")
    print(f"RECORDING {label}: {abs(signed_seconds)} seconds. WALK NOW!", flush=True)
    # Do NOT call Bridge during acquisition (interruptions may lose samples).
    time.sleep(abs(signed_seconds) + 0.3)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = status()
        if int(result[1]) == 2:
            return result
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {label} acquisition; last={result}")


def run_trial():
    if PERSON not in LABELS:
        raise ValueError(f"Unknown PERSON={PERSON!r}; choose one of {sorted(LABELS)}")
    if not 2 <= CAPTURE_SECONDS <= 10:
        raise ValueError("CAPTURE_SECONDS must be between 2 and 10")

    # The App Lab /app directory is mapped to the host's ArduinoApps/<APP>/.
    # Unlike /home/arduino in the Python container, data saved here is visible
    # to `adb pull` from the host Linux filesystem.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = DATA_ROOT / PERSON / f"session_{timestamp}"
    suffix = 2
    while dest.exists():
        dest = DATA_ROOT / PERSON / f"session_{timestamp}_{suffix}"
        suffix += 1
    dest.mkdir(parents=True, exist_ok=False)
    print("Persistent dataset directory (App container):", dest, flush=True)
    print("ADB host directory:",
          f"/home/arduino/ArduinoApps/{APP_NAME}/data/footstep_dataset", flush=True)

    metadata = {
        "person_id": PERSON,
        "capture_mode": "sequential_audio_then_sensors",
        "capture_seconds": CAPTURE_SECONDS,
        "audio_phase_seconds": CAPTURE_SECONDS,
        "sensor_phase_seconds": CAPTURE_SECONDS,
        "rates_hz": {"audio": AUDIO_RATE, "microphone": ANALOG_RATE,
                     "piezo": ANALOG_RATE, "mpu6050": MPU_RATE},
        "time_alignment": "UNSYNCED: WAV and sensor CSVs are different walking passes. Each starts its own t=0.",
        "timestamp_type": "nominal sample slots, NOT measured ADC timestamps",
        "acquisition": "best-effort micros scheduling; not hardware DMA/timer sampling",
        "recording_status": "starting",
    }
    write_json(dest / "metadata.json", metadata)
    first = status()
    if not first[9]:
        print("WARNING: MPU6050 not detected; MPU data will be missing.", flush=True)

    audio_status = capture_phase("PHASE 1/2: AUDIO ONLY (A0 6000 Hz)", +CAPTURE_SECONDS)
    if int(audio_status[15]) != 1 or int(audio_status[14]) != 1:
        raise RuntimeError(f"Audio phase did not complete: {audio_status}")
    audio_missing = int(audio_status[5])
    audio_total = CAPTURE_SECONDS * AUDIO_RATE
    audio_missing_fraction = audio_missing / audio_total
    print(f"AUDIO: {audio_missing}/{audio_total} missed ({audio_missing_fraction:.2%}); "
          f"valid sampling ~{AUDIO_RATE*(1-audio_missing_fraction):.0f} samples/second", flush=True)
    if audio_missing_fraction >= MAX_MISSING_RATE:
        print("WARNING: AUDIO QUALITY INVALID for acoustic model training. "
              "WAV will be saved for inspection only.", flush=True)

    sensor_status = capture_phase("PHASE 2/2: MIC+PIEZO+MPU CSV", -CAPTURE_SECONDS)
    if int(sensor_status[16]) != 1 or int(sensor_status[14]) != 2:
        raise RuntimeError(f"Sensor phase did not complete: {sensor_status}")
    n_audio = CAPTURE_SECONDS * AUDIO_RATE
    n_analog = CAPTURE_SECONDS * ANALOG_RATE
    n_mpu = CAPTURE_SECONDS * MPU_RATE
    got = (int(sensor_status[2]), int(sensor_status[3]), int(sensor_status[4]))
    if got != (n_audio, n_analog, n_mpu):
        raise RuntimeError(f"Sample count mismatch: {got} expected {(n_audio, n_analog, n_mpu)}")

    misses = {"audio": int(sensor_status[5]),
              "analog": int(sensor_status[6]),
              "mpu_deadlines": int(sensor_status[7]),
              "mpu_read_errors": int(sensor_status[8])}
    for name, count, total in (("audio", misses["audio"], n_audio),
                              ("analog", misses["analog"], n_analog),
                              ("mpu", misses["mpu_deadlines"] + misses["mpu_read_errors"], n_mpu)):
        print(f"{name}: {count}/{total} missing/error slots ({100*count/total:.2f}%)", flush=True)

    metadata["recording_status"] = "recorded_pending_transfer"
    metadata["mpu_ready"] = bool(sensor_status[9])
    metadata["missed"] = misses
    metadata["audio_usable_for_training"] = audio_missing_fraction < MAX_MISSING_RATE
    metadata["samples"] = {"audio": n_audio, "microphone": n_analog,
                           "piezo": n_analog, "mpu6050": n_mpu}
    write_json(dest / "metadata.json", metadata)
    print("Acquisition complete. Downloading MCU buffers over Bridge. "
          "Keep App Lab running until SAVED is printed.", flush=True)

    audio = read_chunks(1, n_audio, 40)
    wav_info = write_wav(dest / "audio.wav", audio)
    print("Saved audio.wav", flush=True)
    analog = read_chunks(2, n_analog, 40)
    write_adc_csv(dest / "microphone.csv", PERSON, [v[0] for v in analog])
    write_adc_csv(dest / "piezo.csv", PERSON, [v[1] for v in analog])
    print("Saved microphone.csv and piezo.csv", flush=True)
    mpu = read_chunks(3, n_mpu, 13)
    write_mpu_csv(dest / "mpu6050.csv", PERSON, mpu)
    print("Saved mpu6050.csv", flush=True)

    metadata.update(wav_info)
    metadata["recording_status"] = "complete"
    write_json(dest / "metadata.json", metadata)
    print("\nSAVED COMPLETE SESSION:", dest, flush=True)
    print("Transfer from your PC:", flush=True)
    print(f"adb pull /home/arduino/ArduinoApps/{APP_NAME}/data/footstep_dataset ./footstep_dataset", flush=True)
    if not metadata["audio_usable_for_training"]:
        print("NOTE: Do NOT train acoustic model on this WAV (high dropout). "
              "Check missing rate before collecting the dataset.", flush=True)



def cloud_pack_session(session):
    """ZIP exact training files and split into ThingSpeak string fields."""
    if json.loads((session / "metadata.json").read_text()).get("recording_status") != "complete":
        raise RuntimeError("Refusing incomplete recording")
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for filename in CLOUD_FILE_NAMES:
            archive.write(session / filename, arcname=filename)
    blob = memory.getvalue()
    checksum = hashlib.sha256(blob).hexdigest()
    session_id = checksum[:16]
    encoded = base64.b64encode(blob).decode("ascii")
    slice_len = CLOUD_PART_CHARS * CLOUD_FIELDS_PER_ENTRY
    pieces = [encoded[i:i + slice_len] for i in range(0, len(encoded), slice_len)]
    if not pieces or len(pieces) > CLOUD_MAX_ENTRIES:
        raise RuntimeError(f"Recording requires {len(pieces)} ThingSpeak entries; "
                           f"limit is {CLOUD_MAX_ENTRIES}; keep the files locally instead")
    updates = []
    for number, piece in enumerate(pieces):
        entry = {"delta_t": 1,
                 "field8": f"FS1|{session_id}|{number}|{len(pieces)}|{checksum}"}
        for field in range(CLOUD_FIELDS_PER_ENTRY):
            part = piece[field*CLOUD_PART_CHARS:(field+1)*CLOUD_PART_CHARS]
            if part:
                entry[f"field{field+1}"] = part
        updates.append(entry)
    return session_id, checksum, updates, len(blob)


def post_cloud(session):
    """Upload AFTER recording. The raw session is never deleted."""
    session_id, checksum, updates, compressed_bytes = cloud_pack_session(session)
    if not THINGSPEAK_CHANNEL_ID or not THINGSPEAK_WRITE_KEY:
        print("CLOUD DISABLED: edit THINGSPEAK_CHANNEL_ID and THINGSPEAK_WRITE_KEY in main.py", flush=True)
        return False

    # A bulk request inserts rows with timestamps 1 second apart, ending NOW.
    # Avoid overlapping timestamps with the previous batch on this channel.
    # The NEXT packet count (not the previous packet count) determines how far
    # backward the new batch extends from its final timestamp.
    state = json.loads(CLOUD_STATE_FILE.read_text()) if CLOUD_STATE_FILE.exists() else {}
    if str(state.get("channel_id")) == str(THINGSPEAK_CHANNEL_ID):
        seconds_since = time.time() - float(state.get("posted_at", 0))
        minimum = max(16, len(updates) + 15)
        if seconds_since < minimum:
            seconds_to_wait = minimum - seconds_since
            print(f"Cloud pacing: waiting {seconds_to_wait:.0f} seconds to avoid "
                  "ThingSpeak timestamp collisions", flush=True)
            time.sleep(seconds_to_wait)

    endpoint = (f"https://api.thingspeak.com/channels/"
                f"{int(THINGSPEAK_CHANNEL_ID)}/bulk_update.json")
    body = json.dumps({"write_api_key": THINGSPEAK_WRITE_KEY,
                       "updates": updates}, separators=(",", ":")).encode("utf-8")
    print(f"ThingSpeak upload {session.name}: {len(updates)} entries, "
          f"{compressed_bytes} compressed bytes, {len(body)} HTTP bytes", flush=True)
    request = urllib.request.Request(endpoint, data=body,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
    with urllib.request.urlopen(request, timeout=120) as response:
        http_status = response.status
        raw_reply = response.read().decode("utf-8").strip()
    reply = json.loads(raw_reply) if raw_reply else {}
    # API reference uses {"success": true} with HTTP 200. Some ThingSpeak
    # examples document HTTP 202 as 'accepted for processing'. Neither
    # response alone proves that every cloud packet is already readable.
    if reply.get("success") is False or (reply.get("success") is not True and http_status != 202):
        raise RuntimeError(f"ThingSpeak did not accept bulk upload (HTTP {http_status}): {reply!r}")
    CLOUD_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLOUD_STATE_FILE.write_text(json.dumps({"channel_id": THINGSPEAK_CHANNEL_ID,
                    "posted_at": time.time(), "entry_count": len(updates)}, indent=2))
    (session / "cloud_uploaded.json").write_text(json.dumps({
        "channel_id": THINGSPEAK_CHANNEL_ID, "session_id": session_id,
        "sha256": checksum, "entries": len(updates), "transport": "thingspeak_bulk_v1",
        "verification": "accepted_by_api_not_yet_verified_by_pc",
        "http_status": http_status
    }, indent=2))
    print(f"CLOUD REQUEST ACCEPTED (unverified). Session ID: {session_id}", flush=True)
    print("Retrieve on PC: python -m footstep_id.thingspeak_cli classify --session-id " + session_id,
          flush=True)
    return True


def upload_pending_sessions():
    if not UPLOAD_ENABLED:
        print("Cloud uploading disabled (UPLOAD_ENABLED=False)", flush=True)
        return
    if not THINGSPEAK_CHANNEL_ID or not THINGSPEAK_WRITE_KEY:
        print("No ThingSpeak credentials configured. Sessions remain saved locally.", flush=True)
        return
    pending = sorted(DATA_ROOT.glob("*/session_*/metadata.json"))
    for meta_path in pending:
        folder = meta_path.parent
        if (folder / "cloud_uploaded.json").exists():
            continue
        try:
            if json.loads(meta_path.read_text()).get("recording_status") != "complete":
                continue
            post_cloud(folder)
        except Exception as exc:
            print(f"UPLOAD ERROR for {folder}: {type(exc).__name__}: {exc}", flush=True)
            print("Files remain on UNO Q. Check PC cloud for this session ID "
                  "before attempting another upload (timeouts can be ambiguous).", flush=True)
            # Avoid automatically posting the same session repeatedly when a
            # timeout may have occurred AFTER ThingSpeak accepted it.
            break


def user_loop():
    global already_recorded
    if already_recorded:
        time.sleep(2)
        return
    already_recorded = True
    try:
        if not UPLOAD_ONLY:
            run_trial()
        upload_pending_sessions()
    except Exception as exc:
        print("CAPTURE FAILED:", repr(exc), flush=True)
        raise


if __name__ == "__main__":
    App.run(user_loop=user_loop)
