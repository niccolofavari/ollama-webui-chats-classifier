"""
Phase 4 — Constrained classification
===============================================================================
Input:  output/phase0_chats.json
        output/phase1_extracted.json
        output/phase3_taxonomy.json   ← must have "approved": true
Output: output/phase4_classified.json

What it does:
- Uses the APPROVED taxonomy as a strict vocabulary
- Combines original text + Phase 1 extraction for efficient classification
- Validates that returned categories and tags are in the allowed set
- Records confidence and ambiguities for Phase 5 (QA)
- Checkpoint-based crash recovery every N chats
===============================================================================
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime
from collections import Counter

from config import OUTPUT_DIR, CHECKPOINT_DIR, CHECKPOINT_EVERY, LLM_OPTIONS_CLASSIFY
from logger import get_logger
from utils import (
    load_json, save_json, save_checkpoint, load_checkpoint, clear_checkpoint,
    truncate_smart, llm_call_json, print_header, output_exists, is_force, resolve_model,
)
from validator import sanitize_classification

log = get_logger("phase4")


def build_classification_system(taxonomy: dict) -> tuple[str, list, list, list]:
    """
    Build the classification system prompt from the approved taxonomy.

    Returns:
        (system_prompt, valid_cat_ids, valid_tag_slugs, valid_int_type_ids)
    """
    cats = taxonomy.get("macro_categories", [])
    tags = taxonomy.get("controlled_tags", [])
    int_types = taxonomy.get("interaction_types", [])

    cat_lines: list[str] = []
    valid_cat_ids: list[str] = []
    for cat in cats:
        cat_id = cat["id"]
        valid_cat_ids.append(cat_id)
        subs = cat.get("subcategories", [])
        sub_ids = ", ".join(s["id"] for s in subs) if subs else "none"
        cat_lines.append(
            f"- **{cat_id}** ({cat['name']}): {cat['description']}\n"
            f"  Valid subcategories: {sub_ids}"
        )

    valid_tag_slugs: list[str] = [t["tag"] for t in tags]
    tag_lines = [f"  {t['tag']}: {t['description']}" for t in tags]

    valid_int_ids: list[str] = [i["id"] for i in int_types]
    int_lines = [f"  {i['id']}: {i['description']}" for i in int_types]

    rules = taxonomy.get("classification_rules", [])
    rules_str = "\n".join(f"  {r}" for r in rules) if rules else ""

    system = f"""You are a precise classifier. Classify the conversation using
ONLY the values listed below.

ALLOWED MACRO-CATEGORIES:
{chr(10).join(cat_lines)}

ALLOWED TAGS (choose 3-6 among these, only relevant ones):
{chr(10).join(tag_lines)}

ALLOWED INTERACTION TYPES:
{chr(10).join(int_lines)}

{"RULES:" + chr(10) + rules_str if rules_str else ""}

Return ONLY a JSON object:
{{
  "macro_category": "one of the allowed ids",
  "subcategory": "id of a valid subcategory for this category, or null",
  "tags": ["tag1", "tag2", "tag3"],
  "interaction_type": "one of the allowed ids",
  "confidence": "high|medium|low",
  "ambiguity_note": "only if confidence is low: explain the doubt; otherwise null"
}}

⚠️ REQUIRED: use values exactly as written in the lists above.
If unsure between two categories, choose the more specific one and set confidence to "medium"."""

    return system, valid_cat_ids, valid_tag_slugs, valid_int_ids


def classify_single(
    chat: dict,
    phase1_data: dict | None,
    system_prompt: str,
    valid_cat_ids: list,
    valid_tag_slugs: list,
    valid_int_ids: list,
) -> dict:
    """
    Classify one conversation and validate the output against the taxonomy vocabulary.
    Returns a sanitized classification dict — never raises on validation errors.
    May raise RuntimeError if the LLM call itself fails after all retries.
    """
    text = truncate_smart(chat["full_text"], max_chars=4000)

    phase1_ctx = ""
    if phase1_data:
        topics_str = ", ".join(phase1_data.get("topics", [])[:10])
        entities_str = ", ".join(phase1_data.get("entities", [])[:10])
        phase1_ctx = (
            f"\n\n[PRIOR ANALYSIS]\n"
            f"Summary: {phase1_data.get('summary', '')}\n"
            f"Topics: {topics_str}\n"
            f"Entities: {entities_str}\n"
            f"User intent: {phase1_data.get('user_intent', '')}"
        )

    prompt = (
        f"Title: {chat['title']}\n"
        f"Date: {chat['date']}\n"
        f"AI model used: {', '.join(chat.get('models', ['?']))}\n"
        f"{phase1_ctx}\n\n"
        f"CONVERSATION:\n\n{text}\n\n"
        f"Classify this conversation."
    )

    raw = llm_call_json(
        prompt=prompt,
        system=system_prompt,
        options=LLM_OPTIONS_CLASSIFY,
        required_fields=["macro_category", "tags", "interaction_type", "confidence"],
        timeout=120,
    )

    return sanitize_classification(
        raw,
        valid_cats=valid_cat_ids,
        valid_tags=valid_tag_slugs,
        valid_int_types=valid_int_ids,
        chat_id=chat.get("id", ""),
        title=chat["title"],
    )


def run() -> None:
    print_header("PHASE 4 — Constrained classification")

    model = resolve_model()
    force = is_force()

    if not force and output_exists("phase4_classified.json"):
        sys.exit(0)

    if force:
        clear_checkpoint("phase4")
        log.info("--force: checkpoint cleared")
        print("⚠️  --force: previous checkpoint cleared, starting over")

    tax_path = Path(OUTPUT_DIR) / "phase3_taxonomy.json"
    tax_obj = load_json(tax_path)

    if not tax_obj.get("approved"):
        log.error("Taxonomy not approved — cannot run phase 4")
        print("❌ Taxonomy not approved!")
        print(f"   Open {tax_path} and set \"approved\": true after reviewing.")
        sys.exit(1)

    taxonomy = tax_obj["taxonomy"]
    system_prompt, valid_cat_ids, valid_tag_slugs, valid_int_ids = \
        build_classification_system(taxonomy)

    print(f"Model:       {model}")
    print(f"Categories:  {valid_cat_ids}")
    print(f"Tags:        {len(valid_tag_slugs)}")
    print(f"Int. types:  {valid_int_ids}")
    log.info(
        "Phase 4 started — model=%s  categories=%d  tags=%d",
        model, len(valid_cat_ids), len(valid_tag_slugs),
    )

    phase0 = load_json(Path(OUTPUT_DIR) / "phase0_chats.json")
    phase1 = load_json(Path(OUTPUT_DIR) / "phase1_extracted.json")
    chats = phase0["chats"]
    total = len(chats)

    phase1_lookup: dict = {
        r["id"]: r.get("extraction", {})
        for r in phase1["results"]
        if r.get("status") == "ok"
    }

    classified: list = load_checkpoint("phase4") or []
    processed_ids = {c["id"] for c in classified}
    if processed_ids:
        print(f"\nResuming from checkpoint: {len(classified)}/{total} already done")
        log.info("Resuming: %d/%d already classified", len(classified), total)

    error_count = sum(1 for c in classified if c.get("_error"))

    print()
    for chat in chats:
        if chat["id"] in processed_ids:
            continue

        n_done = len(classified)
        pct = n_done / total * 100
        print(f"[{n_done+1:3d}/{total}] {pct:4.0f}%  {chat['title'][:50]:<50}", end=" ", flush=True)
        log.info("Classifying [%d/%d]: %s", n_done + 1, total, chat["title"])

        phase1_data = phase1_lookup.get(chat["id"])

        try:
            result = classify_single(
                chat, phase1_data,
                system_prompt, valid_cat_ids, valid_tag_slugs, valid_int_ids,
            )

            conf_icon = {"high": "✓", "medium": "~", "low": "?",
                         "alta": "✓", "media": "~", "bassa": "?"}.get(
                result.get("confidence", ""), "?"
            )
            cat = result.get("macro_category", "?")
            sub = result.get("subcategory") or ""
            sub_str = f"/{sub}" if sub else ""
            print(f"{conf_icon} → {cat}{sub_str}")
            log.info("Classified as '%s%s' (confidence=%s)", cat, sub_str, result.get("confidence"))

            classified.append({
                "id":    chat["id"],
                "title": chat["title"],
                "date":  chat["date"],
                **result,
            })

        except Exception as exc:
            error_count += 1
            error_msg = str(exc)
            print(f"✗ ERROR: {error_msg}")
            log.error("FAILED to classify '%s': %s", chat["title"], error_msg)

            classified.append({
                "id":             chat["id"],
                "title":          chat["title"],
                "date":           chat["date"],
                "macro_category": "_ERROR",
                "tags":           [],
                "confidence":     "none",
                "_error":         error_msg,
            })

        if len(classified) % CHECKPOINT_EVERY == 0:
            save_checkpoint(classified, "phase4")

    cat_dist = Counter(c.get("macro_category", "?") for c in classified)
    conf_dist = Counter(c.get("confidence", "?") for c in classified)

    output = {
        "metadata": {
            "phase": 4,
            "total": len(classified),
            "errors": error_count,
            "model": model,
            "category_distribution": dict(cat_dist.most_common()),
            "confidence_distribution": dict(conf_dist),
            "generated_at": datetime.now().isoformat(),
        },
        "classified": classified,
    }

    out_path = Path(OUTPUT_DIR) / "phase4_classified.json"
    save_json(output, out_path)
    clear_checkpoint("phase4")

    log.info(
        "Phase 4 complete — total=%d  errors=%d  categories=%s",
        len(classified), error_count, dict(cat_dist.most_common(5)),
    )
    print(f"\n✓ Phase 4 complete: {len(classified)} classified, {error_count} errors")
    print(f"\n  Category distribution:")
    total_c = len(classified)
    for cat, count in cat_dist.most_common():
        bar = "█" * int(count / total_c * 40)
        pct = count / total_c * 100
        print(f"    {cat:<30} {count:4d} ({pct:4.0f}%)  {bar}")

    low_conf = sum(1 for c in classified if c.get("confidence") in ("low", "bassa"))
    if low_conf:
        print(f"\n  ⚠ {low_conf} conversations with low confidence → review in Phase 5")

    print(f"\n  → Output: {out_path}")
    print(f"\n  Next step: python phase5_qa.py")


if __name__ == "__main__":
    run()
