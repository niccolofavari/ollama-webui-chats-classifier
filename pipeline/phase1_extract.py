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


def _display_title(title: str, max_len: int = 55) -> str:
    """Return a single-line, printable version of the title for console output."""
    first_line = title.split("\n")[0].strip()
    if len(first_line) > max_len:
        return first_line[:max_len - 1] + "…"
    return first_line


def _content_is_mostly_code(text: str, sample_chars: int = 2000) -> bool:
    """
    Heuristic: if the first sample is mostly HTML/code, return True.
    Triggers a simplified prompt to avoid the LLM getting confused.
    """
    sample = text[:sample_chars]
    html_markers = ("<!DOCTYPE", "<html", "<?php", "###", "class-", ".php", ".js", ".css")
    hits = sum(1 for m in html_markers if m in sample)
    return hits >= 2


def _redact_code_blocks(text: str) -> str:
    """
    Replace code blocks and long PHP/HTML chunks with a short placeholder.
    Keeps only the prose context around the code, which is all the LLM needs
    to understand the conversation topic.
    """
    import re
    # Markdown code fences: ```...```
    text = re.sub(r"```[\s\S]*?```", "[CODE BLOCK OMITTED]", text)
    # Inline PHP tags
    text = re.sub(r"<\?php[\s\S]*?\?>", "[PHP BLOCK OMITTED]", text)
    # Long HTML tags (>100 chars)
    text = re.sub(r"<[^>]{100,}>", "[HTML TAG OMITTED]", text)
    # Lines that look like pure code (start with $, //, namespace, class, function)
    lines = text.split("\n")
    result = []
    code_run = 0
    for line in lines:
        stripped = line.strip()
        is_code_line = (
            stripped.startswith(("$", "//", "/*", "*", "namespace ", "class ", "function ", "<?", "?>", "};", "});"))
            or (len(stripped) > 60 and stripped.count("{") + stripped.count("}") > 2)
        )
        if is_code_line:
            code_run += 1
            if code_run == 1:
                result.append("[... code omitted ...]")
        else:
            code_run = 0
            result.append(line)
    return "\n".join(result)


def extract_single(chat: dict) -> dict:
    """
    Run the LLM extraction for one conversation.
    Returns a sanitized dict — never raises on LLM or parsing errors.
    Raises RuntimeError if the LLM call itself fails after all retries.

    For conversations whose content is mostly code/HTML, uses a simplified
    prompt with a shorter input to avoid the model getting confused.
    """
    full_text = chat["full_text"]
    is_code = _content_is_mostly_code(full_text)

    if is_code:
        # For code-heavy chats: redact code blocks first, then truncate.
        # This prevents the model from echoing PHP/HTML into the JSON output.
        log.info("Code-heavy content detected for '%s' — redacting code blocks", chat["title"][:50])
        redacted = _redact_code_blocks(full_text)
        text = truncate_smart(redacted, max_chars=3000)
    else:
        text = truncate_smart(full_text)

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
        f"Conversation title: {chat['title'][:200]}\n"
        f"Date: {chat['date']}\n"
        f"Model used: {', '.join(chat.get('models', ['unknown']))}\n"
        f"Messages: {chat.get('n_messages', '?')}\n"
        f"{tag_context}\n\n"
        f"CONVERSATION:\n\n{text}"
    )

    raw = llm_call_json(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        options=LLM_OPTIONS_EXTRACT,
        required_fields=["summary", "topics", "entities", "user_intent"],
        timeout=90,  # hard cap per chat — prevents indefinite hangs
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

        display = _display_title(chat["title"])
        print(f"[{n_done+1:3d}/{total}] {pct:4.0f}%  {display:<55}", end=" ", flush=True)
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
