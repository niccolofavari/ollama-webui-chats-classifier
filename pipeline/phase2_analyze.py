"""
Phase 2 — Corpus analysis
===============================================================================
Input:  output/phase1_extracted.json
Output: output/phase2_analysis.json
        output/phase2_readable.md   (human-readable summary)

What it does:
1. Collects raw statistics from Phase 1 extractions (pure frequency analysis)
2. Asks the LLM to group synonyms and identify thematic patterns
3. Analyzes interaction type variety
4. Produces a readable document to guide taxonomy construction in Phase 3

Does NOT classify yet — only prepares the ground.
===============================================================================
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime
from collections import Counter

from config import OUTPUT_DIR, CLUSTER_BATCH_SIZE, LLM_OPTIONS_CLUSTER
from logger import get_logger
from utils import (
    load_json, save_json, llm_call_json, print_header, output_exists, is_force, resolve_model,
)

log = get_logger("phase2")


def collect_statistics(results: list) -> dict:
    """Collect raw corpus statistics from Phase 1 results (no LLM)."""
    topic_counter: Counter = Counter()
    entity_counter: Counter = Counter()
    interaction_types: list[str] = []
    existing_tag_counter: Counter = Counter()
    multi_topic_count = 0
    language_counter: Counter = Counter()

    for r in results:
        if r.get("status") != "ok":
            continue
        ex = r.get("extraction", {})

        for t in ex.get("topics", []):
            if isinstance(t, str) and t.strip():
                topic_counter[t.lower().strip()] += 1

        for e in ex.get("entities", []):
            if isinstance(e, str) and e.strip():
                entity_counter[e.strip()] += 1

        it = ex.get("interaction_type", "")
        if isinstance(it, str) and it.strip():
            interaction_types.append(it.strip())

        for tag in r.get("existing_tags", []):
            if isinstance(tag, str) and tag.strip():
                existing_tag_counter[tag.lower().strip()] += 1

        if ex.get("multi_topic"):
            multi_topic_count += 1

        # language may be a list if the LLM misbehaved — already sanitized in phase1,
        # but guard here too for robustness
        lang = ex.get("language", "")
        if isinstance(lang, list):
            lang = lang[0] if lang else ""
            log.warning("'language' field was a list in result id=%s", r.get("id", "?"))
        if isinstance(lang, str) and lang.strip():
            language_counter[lang.lower().strip()] += 1

    return {
        "topic_frequencies":        dict(topic_counter.most_common()),
        "entity_frequencies":       dict(entity_counter.most_common()),
        "interaction_types_raw":    interaction_types,
        "existing_tag_frequencies": dict(existing_tag_counter.most_common()),
        "multi_topic_count":        multi_topic_count,
        "language_distribution":    dict(language_counter.most_common()),
    }


def cluster_topics(topic_freq: dict) -> list:
    """
    Group topics into synonym/concept clusters using the LLM.
    Works in batches to stay within the context window.
    """
    all_items = [
        f"{topic} ({count}x)"
        for topic, count in sorted(topic_freq.items(), key=lambda x: -x[1])
    ]

    all_clusters: list = []
    total_batches = (len(all_items) + CLUSTER_BATCH_SIZE - 1) // CLUSTER_BATCH_SIZE
    log.info("Clustering %d unique topics in %d batches", len(all_items), total_batches)
    print(f"  Clustering {len(all_items)} unique topics in {total_batches} batches...")

    for batch_start in range(0, len(all_items), CLUSTER_BATCH_SIZE):
        batch = all_items[batch_start : batch_start + CLUSTER_BATCH_SIZE]
        batch_num = batch_start // CLUSTER_BATCH_SIZE + 1
        print(f"    Batch {batch_num}/{total_batches}...", end=" ", flush=True)

        prompt = f"""Here is a list of topics extracted from a conversation corpus
(frequency in parentheses):

{chr(10).join(batch)}

TASK:
1. Group terms that are synonyms, language variants, or refer to the same concept
   (e.g. "python programming" and "python scripting" → same cluster)
2. For each group, choose the clearest canonical name
3. Identify the macro-themes that emerge naturally from the data

Return ONLY a JSON object:
{{
  "synonym_groups": [
    {{
      "canonical": "chosen canonical name",
      "members": ["variant1", "variant2"],
      "total_occurrences": 42
    }}
  ],
  "standalone": ["topic with no synonyms but still significant"],
  "suggested_themes": [
    {{
      "theme": "theme name",
      "rationale": "why these topics belong together",
      "canonical_topics": ["canonical1", "canonical2"]
    }}
  ]
}}"""

        try:
            result = llm_call_json(
                prompt=prompt,
                options=LLM_OPTIONS_CLUSTER,
                required_fields=["synonym_groups"],
                timeout=240,
            )
            all_clusters.append(result)
            n_groups = len(result.get("synonym_groups", []))
            n_themes = len(result.get("suggested_themes", []))
            log.info("Batch %d: %d groups, %d themes", batch_num, n_groups, n_themes)
            print(f"✓  {n_groups} groups, {n_themes} themes")
        except Exception as exc:
            log.error("Batch %d failed: %s", batch_num, exc)
            print(f"✗  {exc}")
            all_clusters.append({"error": str(exc), "batch_start": batch_start})

    return all_clusters


def analyze_interaction_types(raw_types: list) -> dict:
    """Group freely-described interaction types into coherent categories."""
    type_freq = Counter(t.strip().lower() for t in raw_types if t.strip())
    top_types = [f"{t} ({c}x)" for t, c in type_freq.most_common(80)]
    log.info("Analyzing %d unique interaction types", len(type_freq))

    prompt = f"""Here are descriptions of interaction types from a conversation corpus:

{chr(10).join(top_types)}

TASK:
Group these descriptions into coherent interaction categories.
Categories must emerge from the data — do not invent ones that are not present.

Return ONLY a JSON object:
{{
  "interaction_categories": [
    {{
      "canonical_name": "short clear name",
      "description": "when this category applies",
      "examples": ["example1", "example2"],
      "frequency_estimate": "high/medium/low"
    }}
  ]
}}"""

    try:
        return llm_call_json(
            prompt=prompt,
            options=LLM_OPTIONS_CLUSTER,
            required_fields=["interaction_categories"],
            timeout=180,
        )
    except Exception as exc:
        log.error("Interaction type analysis failed: %s", exc)
        return {"error": str(exc), "raw_top": top_types[:20]}


def generate_readable_report(stats: dict, clusters: list, interactions: dict) -> str:
    """Generate a human-readable markdown document for review before Phase 3."""
    lines = [
        "# CORPUS ANALYSIS — Phase 2",
        "",
        "> Use this document as input when reviewing the taxonomy proposal in Phase 3.",
        "> Run `python phase3_taxonomy.py` next.",
        "",
        "---",
        "",
        "## Statistics",
        "",
    ]

    lang_dist = stats.get("language_distribution", {})
    lines.append("**Languages detected:**")
    for lang, count in list(lang_dist.items())[:10]:
        lines.append(f"- {lang}: {count} conversations")

    lines += [
        "",
        f"**Multi-topic conversations:** {stats.get('multi_topic_count', 0)}",
        "",
        "---",
        "",
        "## Top 50 topics (raw frequency)",
        "",
    ]
    for topic, count in list(stats["topic_frequencies"].items())[:50]:
        bar = "█" * min(count, 30)
        lines.append(f"- `{topic}` — {count}x  {bar}")

    lines += ["", "---", "", "## Top 30 entities", ""]
    for entity, count in list(stats["entity_frequencies"].items())[:30]:
        lines.append(f"- **{entity}** — {count}x")

    lines += ["", "---", "", "## Existing tags (from Open WebUI)", ""]
    for tag, count in list(stats["existing_tag_frequencies"].items())[:40]:
        lines.append(f"- `{tag}` — {count}x")

    lines += ["", "---", "", "## LLM-suggested thematic clusters", ""]
    for i, batch in enumerate(clusters):
        if "error" in batch:
            lines.append(f"- ⚠️ Batch {i+1}: error — {batch['error']}")
            continue
        for theme in batch.get("suggested_themes", []):
            lines.append(f"### {theme.get('theme', '?')}")
            lines.append(f"*{theme.get('rationale', '')}*")
            for t in theme.get("canonical_topics", []):
                lines.append(f"- {t}")
            lines.append("")

    lines += ["", "---", "", "## Interaction types", ""]
    for cat in interactions.get("interaction_categories", []):
        lines.append(
            f"### {cat.get('canonical_name', '?')} ({cat.get('frequency_estimate', '?')})"
        )
        lines.append(cat.get("description", ""))
        examples = cat.get("examples", [])
        if examples:
            lines.append(f"*E.g.: {', '.join(examples[:3])}*")
        lines.append("")

    lines += [
        "---",
        "",
        "## Next step",
        "",
        "Run `python phase3_taxonomy.py` to generate the proposed taxonomy.",
        "Then **review** `REVIEW_TAXONOMY.md` before proceeding.",
    ]

    return "\n".join(lines)


def run() -> None:
    print_header("PHASE 2 — Corpus analysis")

    if output_exists("phase2_analysis.json", force=is_force()):
        sys.exit(0)

    model = resolve_model()
    print(f"Model: {model}")

    phase1 = load_json(Path(OUTPUT_DIR) / "phase1_extracted.json")
    results = phase1["results"]
    ok_results = [r for r in results if r.get("status") == "ok"]

    print(f"Valid conversations: {len(ok_results)}/{len(results)}")
    log.info("Phase 2 started — valid=%d  total=%d", len(ok_results), len(results))

    print("\n[1/3] Collecting raw statistics...")
    stats = collect_statistics(results)
    print(f"  Unique topics:   {len(stats['topic_frequencies'])}")
    print(f"  Unique entities: {len(stats['entity_frequencies'])}")
    print(f"  Languages:       {list(stats['language_distribution'].keys())[:5]}")
    log.info(
        "Statistics: topics=%d  entities=%d  languages=%s",
        len(stats["topic_frequencies"]),
        len(stats["entity_frequencies"]),
        list(stats["language_distribution"].keys())[:5],
    )

    print("\n[2/3] Clustering topics with LLM...")
    clusters = cluster_topics(stats["topic_frequencies"])
    cluster_errors = sum(1 for c in clusters if "error" in c)
    if cluster_errors:
        log.warning("%d cluster batch(es) failed", cluster_errors)

    print("\n[3/3] Analyzing interaction types...")
    interactions = analyze_interaction_types(stats["interaction_types_raw"])
    n_int_cats = len(interactions.get("interaction_categories", []))
    print(f"  Interaction categories found: {n_int_cats}")
    log.info("Interaction categories: %d", n_int_cats)

    output = {
        "metadata": {
            "phase": 2,
            "valid_results": len(ok_results),
            "unique_topics": len(stats["topic_frequencies"]),
            "unique_entities": len(stats["entity_frequencies"]),
            "generated_at": datetime.now().isoformat(),
        },
        "statistics": stats,
        "topic_clusters": clusters,
        "interaction_analysis": interactions,
    }

    out_path = Path(OUTPUT_DIR) / "phase2_analysis.json"
    save_json(output, out_path)

    report = generate_readable_report(stats, clusters, interactions)
    report_path = Path(OUTPUT_DIR) / "phase2_readable.md"
    report_path.write_text(report, encoding="utf-8")

    log.info("Phase 2 complete — output=%s", out_path)
    print(f"\n✓ Phase 2 complete")
    print(f"  → Data:   {out_path}")
    print(f"  → Report: {report_path}")
    print(f"\n  Next step: python phase3_taxonomy.py")


if __name__ == "__main__":
    run()
