"""
Phase 3 — Taxonomy construction
===============================================================================
Input:  output/phase2_analysis.json
Output: output/phase3_taxonomy.json    ← ⚠️ MUST BE REVIEWED AND APPROVED
        output/REVIEW_TAXONOMY.md      ← human-readable version

What it does:
- The LLM proposes a taxonomy based ONLY on patterns observed in Phase 2
- Generates a markdown file for human review
- The JSON has an "approved": false flag that YOU must change to true
  after reviewing (and optionally editing) the taxonomy

⚠️  Do NOT run Phase 4 before approving this file.
===============================================================================
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime

from config import OUTPUT_DIR, LLM_OPTIONS_TAXONOMY
from logger import get_logger
from utils import (
    load_json, save_json, llm_call_json, print_header, print_action_required,
    is_force, resolve_model,
)

log = get_logger("phase3")


def build_llm_context(analysis: dict) -> str:
    """Summarize the Phase 2 analysis into a compact context string for the LLM."""
    stats = analysis.get("statistics", {})

    top_topics = list(stats.get("topic_frequencies", {}).items())[:60]
    topics_str = "\n".join(f"  - {t} ({c}x)" for t, c in top_topics)

    top_entities = list(stats.get("entity_frequencies", {}).items())[:30]
    entities_str = "\n".join(f"  - {e} ({c}x)" for e, c in top_entities)

    top_existing = list(stats.get("existing_tag_frequencies", {}).items())[:40]
    existing_str = "\n".join(f"  - {t} ({c}x)" for t, c in top_existing)

    clusters = analysis.get("topic_clusters", [])
    theme_parts = []
    for batch in clusters:
        for theme in batch.get("suggested_themes", []):
            name = theme.get("theme", "?")
            rationale = theme.get("rationale", "")
            topics_list = ", ".join(theme.get("canonical_topics", [])[:5])
            theme_parts.append(f"  - **{name}**: {rationale} (e.g.: {topics_list})")
    themes_str = "\n".join(theme_parts) if theme_parts else "  (none)"

    int_cats = analysis.get("interaction_analysis", {}).get("interaction_categories", [])
    int_str = "\n".join(
        f"  - {c.get('canonical_name', '?')}: {c.get('description', '')}"
        for c in int_cats
    )

    lang_dist = stats.get("language_distribution", {})
    lang_str = ", ".join(f"{lang} ({c})" for lang, c in list(lang_dist.items())[:5])

    return f"""CORPUS STATISTICS:
- Languages: {lang_str}
- Unique topics extracted: {len(stats.get('topic_frequencies', {}))}
- Multi-topic conversations: {stats.get('multi_topic_count', 0)}

TOP TOPICS (by frequency):
{topics_str}

MOST CITED SPECIFIC ENTITIES:
{entities_str}

TAGS ALREADY IN OPEN WEBUI:
{existing_str}

THEMATIC CLUSTERS FROM CLUSTERING:
{themes_str}

INTERACTION TYPES DETECTED:
{int_str}"""


def propose_taxonomy(context: str) -> dict:
    """Ask the LLM to propose a taxonomy based on the corpus analysis."""
    prompt = f"""You are a digital librarian. Design a taxonomy to organize a personal
archive of AI conversations.

Here is the corpus analysis:

{context}

GOAL: propose a taxonomy that:
1. Emerges FROM THE DATA (do not invent categories absent from the corpus)
2. Has 6-12 macro-categories (manageable mentally)
3. Each macro-category has specific subcategories
4. Includes a "Miscellaneous" macro-category for outliers
5. Has a controlled tag vocabulary (30-60 tags, precise and non-redundant)
6. Is balanced: no category should contain >40% of conversations
7. Has CLEAR, unambiguous classification criteria

Return ONLY a JSON object:
{{
  "taxonomy_notes": "notes on the corpus and choices made",
  "macro_categories": [
    {{
      "id": "slug-lowercase",
      "name": "Human Readable Name",
      "description": "Precise criteria: a conversation belongs here when...",
      "subcategories": [
        {{
          "id": "slug",
          "name": "Name",
          "description": "specific criteria",
          "example_entities": ["tool1", "technology2"]
        }}
      ]
    }}
  ],
  "controlled_tags": [
    {{
      "tag": "tag-slug",
      "description": "exactly what this represents",
      "merged_from": ["synonym1", "synonym2"]
    }}
  ],
  "interaction_types": [
    {{
      "id": "slug",
      "name": "Name",
      "description": "criterion"
    }}
  ],
  "classification_rules": [
    "Rule 1: if the conversation covers X, put it in category Y",
    "Rule 2: when in doubt between A and B, choose based on..."
  ]
}}"""

    return llm_call_json(
        prompt=prompt,
        options=LLM_OPTIONS_TAXONOMY,
        required_fields=["macro_categories", "controlled_tags"],
        timeout=360,
    )


def generate_readable_taxonomy(taxonomy: dict) -> str:
    """Generate a human-readable markdown review document."""
    lines = [
        "# PROPOSED TAXONOMY — REVIEW REQUIRED",
        "",
        "> **Instructions:**",
        "> 1. Read this proposal carefully",
        "> 2. Edit `phase3_taxonomy.json` as needed",
        "> 3. Change `\"approved\": false` to `\"approved\": true`",
        "> 4. Only then run `python phase4_classify.py`",
        "",
        "---",
        "",
    ]

    notes = taxonomy.get("taxonomy_notes", "")
    if notes:
        lines += ["## LLM notes on the corpus", "", notes, ""]

    lines += ["## Macro-categories", ""]
    for cat in taxonomy.get("macro_categories", []):
        lines.append(f"### `{cat.get('id', '?')}` — {cat.get('name', '?')}")
        lines.append(f"**Criteria:** {cat.get('description', '')}")
        lines.append("")
        subs = cat.get("subcategories", [])
        if subs:
            lines.append("**Subcategories:**")
            for sub in subs:
                examples = sub.get("example_entities", [])
                ex_str = f" *(e.g.: {', '.join(examples[:4])})*" if examples else ""
                lines.append(
                    f"- `{sub.get('id', '?')}` — {sub.get('name', '?')}: "
                    f"{sub.get('description', '')}{ex_str}"
                )
            lines.append("")

    lines += ["---", "", "## Controlled tag vocabulary", ""]
    for tag_obj in taxonomy.get("controlled_tags", []):
        merged = tag_obj.get("merged_from", [])
        merged_str = f" *(includes: {', '.join(merged)})*" if merged else ""
        lines.append(
            f"- `{tag_obj.get('tag', '?')}` — {tag_obj.get('description', '')}{merged_str}"
        )

    lines += ["", "---", "", "## Interaction types", ""]
    for it in taxonomy.get("interaction_types", []):
        lines.append(
            f"- `{it.get('id', '?')}` — **{it.get('name', '?')}**: {it.get('description', '')}"
        )

    rules = taxonomy.get("classification_rules", [])
    if rules:
        lines += ["", "---", "", "## Classification rules", ""]
        for rule in rules:
            lines.append(f"- {rule}")

    return "\n".join(lines)


def run() -> None:
    print_header("PHASE 3 — Taxonomy construction")

    force = is_force()
    tax_path = Path(OUTPUT_DIR) / "phase3_taxonomy.json"

    # Guard: do not overwrite an approved taxonomy without explicit --force
    if tax_path.exists():
        existing = load_json(tax_path)
        if existing.get("approved") and not force:
            log.info("Taxonomy already approved — skipping generation")
            print("✅ Taxonomy already approved — not overwriting.")
            print("   To regenerate from scratch: python phase3_taxonomy.py --force")
            print("   ⚠️  --force will reset 'approved: false' and require re-approval.")
            sys.exit(0)
        elif not existing.get("approved") and not force:
            log.info("Unapproved taxonomy found — waiting for human review")
            print("⚠️  An unapproved taxonomy already exists.")
            print(f"   → To approve it: edit {tax_path} and set \"approved\": true")
            print(f"   → To regenerate: python phase3_taxonomy.py --force")
            sys.exit(0)
        elif force and existing.get("approved"):
            log.warning("--force overwriting an approved taxonomy")
            print("⚠️  --force: the approved taxonomy will be overwritten.")
            print("   You will need to re-approve before running Phase 4.")

    model = resolve_model()
    analysis = load_json(Path(OUTPUT_DIR) / "phase2_analysis.json")

    print(f"Model: {model}")
    log.info("Phase 3 started — model=%s", model)

    print("Building context from corpus analysis...")
    context = build_llm_context(analysis)

    print("Asking LLM to propose a taxonomy...")
    taxonomy = propose_taxonomy(context)

    n_cats = len(taxonomy.get("macro_categories", []))
    n_tags = len(taxonomy.get("controlled_tags", []))
    n_int = len(taxonomy.get("interaction_types", []))
    log.info("Taxonomy proposed: categories=%d  tags=%d  interaction_types=%d", n_cats, n_tags, n_int)
    print(f"  Macro-categories:  {n_cats}")
    print(f"  Controlled tags:   {n_tags}")
    print(f"  Interaction types: {n_int}")

    output = {
        "metadata": {
            "phase": 3,
            "generated_at": datetime.now().isoformat(),
            "model": model,
            "instructions": [
                "1. Read REVIEW_TAXONOMY.md in the output/ folder",
                "2. Edit this file if needed",
                "3. Change 'approved' from false to true",
                "4. Run pipeline/phase4_classify.py",
            ],
        },
        "approved": False,
        "taxonomy": taxonomy,
    }

    save_json(output, tax_path)

    readable = generate_readable_taxonomy(taxonomy)
    readable_path = Path(OUTPUT_DIR) / "REVIEW_TAXONOMY.md"
    readable_path.write_text(readable, encoding="utf-8")

    log.info("Phase 3 complete — %s", tax_path)
    print(f"\n✓ Phase 3 complete")
    print(f"  → JSON:   {tax_path}")
    print(f"  → Review: {readable_path}")

    print_action_required([
        "1. Read output/REVIEW_TAXONOMY.md",
        "2. Edit output/phase3_taxonomy.json if needed",
        "3. Set \"approved\": true in the JSON",
        "4. Then run: python phase4_classify.py",
    ])


if __name__ == "__main__":
    run()
