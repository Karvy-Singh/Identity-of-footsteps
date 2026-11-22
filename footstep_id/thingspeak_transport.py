"""ThingSpeak-only batch transport for full footstep sessions.

Each bulk-write feed entry holds <=240 base64 chars in fields 1..7, with
an 'FS1|...' descriptor in field8. These are NOT native sample rows; each
entry is one transport packet of a ZIP. Checksums guard missing/corrupt data.

No cloud services are used beyond ThingSpeak. Costs many channel messages.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

FIELD_CHARS = 240
DATA_FIELDS = 7
MAX_ENTRIES_PER_POST = 900  # Stay under free-tier bulk limit 960
FILES = ("audio.wav", "microphone.csv", "piezo.csv", "mpu6050.csv", "metadata.json")
MARKER = re.compile(r"^FS1\|([0-9a-f]{16})\|(\d+)\|(\d+)\|([0-9a-f]{64})$")
LABELS = {"Harsh", "Karvy", "Rudra", "No Footsteps"}


def session_to_zip(folder: Path) -> bytes:
    folder = Path(folder)
    meta = json.loads((folder / "metadata.json").read_text())
    if meta.get("recording_status") != "complete":
        raise ValueError("Only completed sessions can be uploaded")
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for filename in FILES:
            archive.write(folder / filename, arcname=filename)
    return data.getvalue()


def zip_to_updates(blob: bytes) -> tuple[str, list[dict]]:
    digest = hashlib.sha256(blob).hexdigest()
    session_id = digest[:16]
    ascii_data = base64.b64encode(blob).decode("ascii")
    chunksize = FIELD_CHARS * DATA_FIELDS
    pieces = [ascii_data[i:i+chunksize] for i in range(0, len(ascii_data), chunksize)]
    if not pieces or len(pieces) > MAX_ENTRIES_PER_POST:
        raise ValueError(f"This session requires {len(pieces)} entries, max {MAX_ENTRIES_PER_POST}. "
                         "Use file/object storage instead of ThingSpeak for larger sessions.")
    entries = []
    for index, piece in enumerate(pieces):
        item = {"delta_t": 1, "field8": f"FS1|{session_id}|{index}|{len(pieces)}|{digest}"}
        for slot in range(DATA_FIELDS):
            chunk = piece[slot*FIELD_CHARS:(slot+1)*FIELD_CHARS]
            if chunk:
                item[f"field{slot+1}"] = chunk
        entries.append(item)
    return session_id, entries


def decode_feeds(feeds: list[dict]) -> dict[str, dict]:
    """Index packets by content hash. Incomplete sessions remain listed."""
    groups = defaultdict(lambda: {"chunks": {}, "errors": []})
    for feed in feeds:
        marker = feed.get("field8")
        if not marker or not (parsed := MARKER.fullmatch(str(marker))):
            continue
        session_id, idx_str, total_str, digest = parsed.groups()
        index, total = int(idx_str), int(total_str)
        if not 0 <= index < total <= MAX_ENTRIES_PER_POST or digest[:16] != session_id:
            continue
        group = groups[session_id]
        if "total" in group and (group["total"] != total or group["sha256"] != digest):
            group["errors"].append("conflicting packet manifests")
            continue
        group["total"] = total
        group["sha256"] = digest
        payload = "".join(str(feed.get(f"field{i}") or "") for i in range(1, 8))
        if index in group["chunks"] and group["chunks"][index] != payload:
            group["errors"].append(f"conflicting packet at index {index}")
        group["chunks"][index] = payload
        group["last_created_at"] = max(str(feed.get("created_at") or ""),
                                       group.get("last_created_at", ""))
    return dict(groups)


def restore_session(group: dict, destination: Path) -> Path:
    """Recreate exact WAV/CSVs; reject corrupt or incomplete uploads."""
    missing = sorted(set(range(group["total"])) - set(group["chunks"]))
    if missing or group["errors"]:
        raise ValueError(f"Cloud session incomplete/corrupt. Missing chunks: {missing[:15]}; "
                         f"errors: {group['errors']}")
    encoded = "".join(group["chunks"][i] for i in range(group["total"]))
    blob = base64.b64decode(encoded, validate=True)
    actual = hashlib.sha256(blob).hexdigest()
    if actual != group["sha256"]:
        raise ValueError("SHA-256 mismatch: remote audio/CSV payload was corrupted")
    with zipfile.ZipFile(io.BytesIO(blob)) as zip_file:
        names = set(zip_file.namelist())
        if names != set(FILES):
            raise ValueError(f"Unexpected archive files: {names}")
        meta = json.loads(zip_file.read("metadata.json"))
        person = meta.get("person_id", "Unknown")
        if person not in LABELS:
            raise ValueError("Unexpected person label in archive")
        # Use a stable, unique content ID to avoid accidental overwrites.
        session_path = Path(destination) / person / f"session_cloud_{actual[:16]}"
        session_path.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            target = session_path / name
            contents = zip_file.read(name)
            if target.exists() and target.read_bytes() != contents:
                raise ValueError(f"Conflicting local file: {target}")
            target.write_bytes(contents)
    return session_path


def fetch_feeds(channel_id: int, read_key: str = "", results: int = 8000,
                start: str = "", end: str = "") -> list[dict]:
    """Read up to a window of feed records from a private or public channel."""
    if not 1 <= results <= 8000:
        raise ValueError("results must be between 1 and 8000")
    params = {"results": str(results)}
    if read_key:
        params["api_key"] = read_key
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    url = f"https://api.thingspeak.com/channels/{int(channel_id)}/feeds.json?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = json.loads(response.read().decode("utf-8"))
    feeds = data.get("feeds")
    if not isinstance(feeds, list):
        raise RuntimeError("ThingSpeak did not return a feeds list. Check channel ID/read key")
    return feeds
