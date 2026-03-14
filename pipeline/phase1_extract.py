"""
Phase 1 — Free extraction
===============================================================================
Input:  output/phase0_chats.json
Output: output/phase1_extracted.json

What it does:
- Asks the LLM to describe each conversation FREELY, with no predefined labels
- No categories are suggested — vocabulary comes entirely from the LLM
- Uses existing meta.tags as context (not as constraints)
- Saves a checkpoint every N chats for crash recovery
===============================================================================
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime

from config import OUTPUT_DIR, CHECKPOINT_DIR, CHECKPOINT_EVERY, LLM_OPTIONS_EXTRACT
from logger import get_logger
from utils import (
    load_json, save_json, save_checkpoint, load_checkpoint, clear_checkpoint,
    truncate_smart, llm_call_json, print_header, output_exists, is_force, resolve_model,
)
from validator import sanitize_extraction, sanitize_title

log = get_logger("phase1")


# ── Prompt — intentionally open-ended, no thematic hints ─────────────────────
SYSTEM_PROMPT = """You are an archivist. Analyze the conversation and return ONLY this JSON (no markdown, no comments):
{
  "summary": "max 20 words",
  "topics": ["3-8 short topics, 2-4 words each"],
  "entities": ["proper names of tools/technologies/people/places, max 10"],
  "user_intent": "max 15 words",
  "interaction_type": "2-4 words (e.g.: technical-help, debug, brainstorming)",
  "language": "single main language",
  "multi_topic": true or false,
  "quality_note": "max 10 words or null"
}"""


def extract_single(chat: dict) -> dict:
    """
    Run the LLM extraction for one conversation.
    Returns a sanitized dict — never raises on LLM or parsing errors.
    Raises RuntimeError if the LLM call itself fails after all retries.
    """
    text = truncate_smart(chat["full_text"])

    # Include existing tags as context (not as constraints)
    tag_context = ""
    if chat.get("existing_tags"):
        tags_str = ", ".join(str(t) for t in chat["existing_tags"])
        tag_context = (
            f"\n\n[NOTE: this conversation already had the following tags "
            f"assigned automatically: {tags_str} — use them as context "
            f"but do not limit yourself to them]"
        )

    prompt = (
        f"Conversation title: {chat['title']}\n"
        f"Date: {chat['date']}\n"
        f"Model used: {', '.join(chat.get('models', ['unknown']))}\n"
        f"{tag_context}\n\n"
        f"CONVERSATION:\n\n{text}"
    )

    raw = llm_call_json(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        options=LLM_OPTIONS_EXTRACT,
        required_fields=["summary", "topics", "entities", "user_intent"],
    )

    return sanitize_extraction(raw, chat_id=chat.get("id", ""), title=chat["title"])


def run() -> None:
    print_header("PHASE 1 — Free extraction")

    model = resolve_model()
    force = is_force()

    # Skip if output already exists — unless there is an unfinished checkpoint
    has_checkpoint = load_checkpoint("phase1") is not None
    if not force and not has_checkpoint and output_exists("phase1_extracted.json"):
        sys.exit(0)

    phase0 = load_json(Path(OUTPUT_DIR) / "phase0_chats.json")
    chats = phase0["chats"]
    total = len(chats)

    print(f"Model:  {model}")
    print(f"Chats:  {total}")
    log.info("Phase 1 started — model=%s  total_chats=%d", model, total)

    if force:
        clear_checkpoint("phase1")
        log.info("--force: checkpoint cleared, restarting from scratch")
        print("⚠️  --force: previous checkpoint cleared, starting over")

    # Resume from checkpoint if available
    results: list[dict] = load_checkpoint("phase1") or []
    processed_ids = {r["id"] for r in results}

    if processed_ids:
        print(f"Resuming from checkpoint: {len(results)}/{total} already done")
        log.info("Resuming: %d/%d already processed", len(results), total)

    error_count = sum(1 for r in results if r.get("status") == "error")

    for chat in chats:
        if chat["id"] in processed_ids:
            continue

        n_done = len(results)
        pct = n_done / total * 100

        # Ensure the title is clean even before LLM extraction
        chat["title"] = sanitize_title(chat.get("title", ""))

        print(f"[{n_done+1:3d}/{total}] {pct:4.0f}%  {chat['title'][:55]:<55}", end=" ", flush=True)
        log.info("Processing [%d/%d]: %s", n_done + 1, total, chat["title"])

        try:
            extraction = extract_single(chat)

            # Normalize topics and entities
            extraction["topics"] = [
                t.strip().lower() for t in extraction.get("topics", []) if t.strip()
            ]
            extraction["entities"] = [
                e.strip() for e in extraction.get("entities", []) if e.strip()
            ]

            n_topics = len(extraction.get("topics", []))
            print(f"✓  {n_topics} topics")
            log.info("OK: %s — %d topics", chat["title"], n_topics)

            results.append({
                "id":            chat["id"],
                "title":         chat["title"],
                "date":          chat["date"],
                "char_count":    chat["char_count"],
                "n_messages":    chat["n_messages"],
                "existing_tags": chat.get("existing_tags", []),
                "status":        "ok",
                "extraction":    extraction,
            })

        except Exception as exc:
            error_count += 1
            error_msg = str(exc)
            print(f"✗  ERROR: {error_msg}")
            log.error("FAILED: %s — %s", chat["title"], error_msg)

            results.append({
                "id":     chat["id"],
                "title":  chat["title"],
                "date":   chat["date"],
                "status": "error",
                "error":  error_msg,
            })

        # Periodic checkpoint
        if len(results) % CHECKPOINT_EVERY == 0:
            save_checkpoint(results, "phase1")

    ok_count = sum(1 for r in results if r["status"] == "ok")

    output = {
        "metadata": {
            "phase": 1,
            "total": total,
            "ok": ok_count,
            "errors": error_count,
            "model": model,
            "generated_at": datetime.now().isoformat(),
        },
        "results": results,
    }

    out_path = Path(OUTPUT_DIR) / "phase1_extracted.json"
    save_json(output, out_path)
    clear_checkpoint("phase1")

    log.info("Phase 1 complete — ok=%d  errors=%d", ok_count, error_count)
    print(f"\n✓ Phase 1 complete: {ok_count}/{total} ok, {error_count} errors")
    print(f"  → Output: {out_path}")
    print(f"\n  Next step: python phase2_analyze.py")


if __name__ == "__main__":
    run()
