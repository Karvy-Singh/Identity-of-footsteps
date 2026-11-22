"""Read ThingSpeak packets and classify completed footstep sessions from CLI.

Examples:
  export THINGSPEAK_CHANNEL_ID=1234
  export THINGSPEAK_READ_KEY=xxxxxxxx
  python -m footstep_id.thingspeak_cli list
  python -m footstep_id.thingspeak_cli pull --latest
  python -m footstep_id.thingspeak_cli classify --latest
"""
import argparse
import json
import os
import sys
from pathlib import Path
from .thingspeak_transport import decode_feeds, fetch_feeds, restore_session


def describe(groups: dict) -> list[tuple[str, dict]]:
    return sorted(groups.items(), key=lambda pair: pair[1].get("last_created_at", ""), reverse=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Restore and classify ThingSpeak footstep recordings")
    parser.add_argument("action", choices=("list", "pull", "classify"))
    parser.add_argument("--channel", type=int, default=int(os.getenv("THINGSPEAK_CHANNEL_ID", "0")))
    parser.add_argument("--read-key", default=os.getenv("THINGSPEAK_READ_KEY", ""), help="Private read key; use environment variable when possible")
    parser.add_argument("--session-id", help="Exact 16-character ID printed by Arduino upload")
    parser.add_argument("--latest", action="store_true", help="Latest FULLY uploaded session")
    parser.add_argument("--all", action="store_true", help="All complete sessions in the fetched channel window")
    parser.add_argument("--dest", type=Path, default=Path("downloaded_sessions"))
    parser.add_argument("--results", type=int, default=8000, help="How many recent ThingSpeak entries to examine")
    parser.add_argument("--start", default="", help="Optional ThingSpeak UTC start (YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--end", default="", help="Optional ThingSpeak UTC end (YYYY-MM-DD HH:MM:SS)")
    args = parser.parse_args(argv)
    if args.channel <= 0:
        parser.error("Set THINGSPEAK_CHANNEL_ID or pass --channel")
    if args.action != "list" and not (args.session_id or args.latest or args.all):
        parser.error("For pull/classify choose --latest, --all, or --session-id ID")
    if sum((bool(args.session_id), args.latest, args.all)) > 1:
        parser.error("Choose only one of --session-id, --latest, or --all")

    print("Retrieving ThingSpeak channel feed...", flush=True)
    groups = decode_feeds(fetch_feeds(args.channel, args.read_key, args.results,
                                     args.start, args.end))
    ranked = describe(groups)
    if args.action == "list":
        if not ranked:
            print("No FS1 packets found. Check keys, channel, or --start/--end range")
        for session_id, entry in ranked:
            count, total = len(entry["chunks"]), entry["total"]
            print(f"{session_id}  {count}/{total} chunks  "
                  f"{'COMPLETE' if count == total and not entry['errors'] else 'INCOMPLETE'} "
                  f"last={entry.get('last_created_at', '-')}")
        return 0

    if args.session_id:
        if args.session_id not in groups:
            raise ValueError("Session ID not in fetched feed; try --results 8000 or --start/--end")
        selected_sessions = [(args.session_id, groups[args.session_id])]
    else:
        full = [(sid, group) for sid, group in ranked
                if len(group["chunks"]) == group["total"] and not group["errors"]]
        if not full:
            raise ValueError("No complete session in retrieved feed. Try increasing --results or use --start/--end")
        selected_sessions = full if args.all else full[:1]
    for selected_id, selected in selected_sessions:
        session_path = restore_session(selected, args.dest)
        print(f"RESTORED verified session {selected_id}: {session_path}", flush=True)
        if args.action == "classify":
            # Prediction runs LOCALLY on PC, never on ThingSpeak/UNO Q.
            from .predict import predict_sequential_session, predict_session, session_summary
            meta = json.loads((session_path / "metadata.json").read_text())
            if meta.get("capture_mode") == "sequential_audio_then_sensors":
                result = predict_sequential_session(session_path)
            else:
                rows = predict_session(session_path)
                result = session_summary(rows)
            output_file = session_path / "prediction.json"
            output_file.write_text(json.dumps(result, indent=2) + "\n")
            for model, info in result.get("per_sensor", {}).items():
                label = max(info["scores"], key=info["scores"].get)
                print(f"  {model:12s} -> {label} ({info['n_windows']} windows)")
            print("PREDICTED:", result["label"])
            print("Models used:", ", ".join(result.get("models_used", [])))
            print("Saved:", output_file)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
