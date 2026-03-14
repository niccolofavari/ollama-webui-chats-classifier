"""
Phase 0 — Split and normalize
===============================================================================
Input:  ../chat-export-*.json  (Open WebUI export)
Output: output/phase0_chats.json

What it does:
- Reads the Open WebUI export file
- Linearizes conversation history (stored as a graph, not a list)
- Extracts objective metadata (dates, counts, models used)
- Preserves any tags already present in meta.tags
- Does NOT interpret content
===============================================================================
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime
from collections import Counter

from config import EXPORT_FILE, OUTPUT_DIR
from logger import get_logger
from utils import (
    load_json, save_json, linearize_messages, build_full_text,
    print_header, output_exists, is_force,
)
from validator import sanitize_title

log = get_logger("phase0")


def run() -> None:
    print_header("PHASE 0 — Split and normalize")

    if output_exists("phase0_chats.json", force=is_force()):
        sys.exit(0)

    export_path = Path(EXPORT_FILE)
    if not export_path.exists():
        export_path = Path("..") / EXPORT_FILE
    if not export_path.exists():
        log.error("Export file not found: %s", EXPORT_FILE)
        print(f"❌ File not found: {EXPORT_FILE}")
        print("   Place the Open WebUI export in the project root.")
        sys.exit(1)

    size_mb = export_path.stat().st_size / 1e6
    print(f"Loading {export_path} ({size_mb:.1f} MB)...")
    log.info("Loading export: %s (%.1f MB)", export_path, size_mb)

    raw_export = load_json(export_path)
    log.info("Export contains %d raw entries", len(raw_export))

    chats = []
    skipped = 0

    for item in raw_export:
        messages = linearize_messages(item)

        if not messages:
            log.debug("Skipping entry (no messages): id=%s", item.get("id", "?"))
            skipped += 1
            continue

        full_text = build_full_text(messages)
        if not full_text.strip():
            log.debug("Skipping entry (empty text): id=%s", item.get("id", "?"))
            skipped += 1
            continue

        # Normalize title — never empty
        raw_title = item.get("title", "")
        title = sanitize_title(raw_title)
        if title != raw_title:
            log.info("Title sanitized: %r → %r", raw_title, title)

        # Timestamps: Open WebUI uses seconds or milliseconds
        def ts_to_str(ts: float | int) -> str:
            if not ts:
                return "unknown"
            if ts > 1e10:
                ts = ts / 1000
            try:
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            except (OSError, OverflowError, ValueError) as exc:
                log.warning("Cannot convert timestamp %r: %s", ts, exc)
                return "unknown"

        created_at = item.get("created_at", 0)
        updated_at = item.get("updated_at", 0)

        models = item.get("chat", {}).get("models", [])
        existing_tags = item.get("meta", {}).get("tags", [])
        role_counts = Counter(m["role"] for m in messages)

        chats.append({
            "id":                    item.get("id", ""),
            "title":                 title,
            "date":                  ts_to_str(created_at),
            "date_updated":          ts_to_str(updated_at),
            "archived":              item.get("archived", False),
            "pinned":                item.get("pinned", False),
            "folder_id":             item.get("folder_id"),
            "models":                models,
            "n_user_messages":       role_counts.get("user", 0),
            "n_assistant_messages":  role_counts.get("assistant", 0),
            "n_messages":            len(messages),
            "char_count":            len(full_text),
            "existing_tags":         existing_tags,
            "full_text":             full_text,
        })

    total = len(chats)
    log.info("Extracted %d chats, skipped %d", total, skipped)

    if total == 0:
        log.error("No chats extracted — check the export file format")
        print("❌ No chats extracted. The export file may be empty or in an unexpected format.")
        sys.exit(1)

    # Summary statistics
    char_counts = sorted(c["char_count"] for c in chats)
    mid = len(char_counts) // 2
    dates = sorted(c["date"] for c in chats if c["date"] != "unknown")
    date_range = f"{dates[0]} → {dates[-1]}" if dates else "unknown"
    has_existing_tags = sum(1 for c in chats if c["existing_tags"])

    output = {
        "metadata": {
            "phase": 0,
            "source_file": str(export_path.name),
            "total_chats": total,
            "skipped": skipped,
            "date_range": date_range,
            "chars_min": char_counts[0],
            "chars_median": char_counts[mid],
            "chars_max": char_counts[-1],
            "chars_total": sum(char_counts),
            "chats_with_existing_tags": has_existing_tags,
            "generated_at": datetime.now().isoformat(),
        },
        "chats": chats,
    }

    out_path = Path(OUTPUT_DIR) / "phase0_chats.json"
    save_json(output, out_path)

    print(f"\n✓ {total} conversations extracted ({skipped} skipped)")
    print(f"  Date range:    {date_range}")
    print(f"  Chars/chat:    min={char_counts[0]:,}  median={char_counts[mid]:,}  max={char_counts[-1]:,}")
    print(f"  Total text:    {sum(char_counts)/1e6:.1f} MB")
    print(f"  With existing tags: {has_existing_tags}/{total}")
    print(f"\n  → Output: {out_path}")
    print(f"\n  Next step: python phase1_extract.py")


if __name__ == "__main__":
    run()
