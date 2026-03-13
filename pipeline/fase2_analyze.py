"""
FASE 2 — Analisi del corpus
═══════════════════════════════════════════════════════════════════════════════
Input:  ../output/fase1_extracted.json
Output: ../output/fase2_analysis.json
        ../output/fase2_readable.md   (per lettura umana)

Cosa fa:
1. Raccoglie tutte le parole/frasi estratte nella Fase 1 (statistica pura)
2. Chiede all'LLM di raggruppare i sinonimi e trovare pattern tematici
3. Analizza i tipi di interazione che emergono
4. Produce un documento leggibile per guidare la costruzione della tassonomia

NON classifica ancora — prepara solo il terreno.
═══════════════════════════════════════════════════════════════════════════════
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime
from collections import Counter
from config import OUTPUT_DIR, CLUSTER_BATCH_SIZE, LLM_OPTIONS_CLUSTER
from utils import load_json, save_json, llm_call_json, print_header, output_exists, is_force, resolve_model


def collect_statistics(results: list) -> dict:
    """Raccoglie statistiche grezze dal corpus (pura analisi frequenze)."""
    all_topics = Counter()
    all_entities = Counter()
    all_interaction_types = []
    all_existing_tags = Counter()
    multi_topic_count = 0
    language_counter = Counter()

    for r in results:
        if r.get("status") != "ok":
            continue
        ex = r.get("extraction", {})

        for t in ex.get("topics", []):
            all_topics[t.lower().strip()] += 1

        for e in ex.get("entities", []):
            all_entities[e.strip()] += 1

        it = ex.get("interaction_type", "")
        if it:
            all_interaction_types.append(it)

        for tag in r.get("existing_tags", []):
            all_existing_tags[tag.lower().strip()] += 1

        if ex.get("multi_topic"):
            multi_topic_count += 1

        lang = ex.get("language", "")
        if lang:
            language_counter[lang.lower()] += 1

    return {
        "topic_frequencies":    dict(all_topics.most_common()),
        "entity_frequencies":   dict(all_entities.most_common()),
        "interaction_types_raw": all_interaction_types,
        "existing_tag_frequencies": dict(all_existing_tags.most_common()),
        "multi_topic_count":    multi_topic_count,
        "language_distribution": dict(language_counter.most_common()),
    }


def cluster_topics(topic_freq: dict) -> list:
    """
    Raggruppa i topics in sinonimi/cluster usando l'LLM.
    Lavora in batch per non superare il contesto.
    """
    # Prendi tutti i topics (con frequenza)
    all_items = [
        f"{topic} ({count}x)"
        for topic, count in sorted(topic_freq.items(), key=lambda x: -x[1])
    ]

    all_clusters = []
    total_batches = (len(all_items) + CLUSTER_BATCH_SIZE - 1) // CLUSTER_BATCH_SIZE

    print(f"  Clustering {len(all_items)} topics unici in {total_batches} batch...")

    for batch_idx in range(0, len(all_items), CLUSTER_BATCH_SIZE):
        batch = all_items[batch_idx:batch_idx + CLUSTER_BATCH_SIZE]
        b_num = batch_idx // CLUSTER_BATCH_SIZE + 1
        print(f"    Batch {b_num}/{total_batches}...", end=" ", flush=True)

        prompt = f"""Ecco una lista di argomenti estratti da un corpus di conversazioni 
(con frequenza tra parentesi):

{chr(10).join(batch)}

COMPITO:
1. Raggruppa i termini che sono sinonimi, varianti linguistiche, o si riferiscono 
   allo stesso concetto (es: "python programming" e "python scripting" → stesso cluster)
2. Per ogni gruppo, scegli il nome canonico più chiaro e preciso
3. Identifica i macro-raggruppamenti tematici che emergono naturalmente

Restituisci SOLO un JSON:
{{
  "synonym_groups": [
    {{
      "canonical": "nome canonico scelto",
      "members": ["variante1", "variante2"],
      "total_occurrences": 42
    }}
  ],
  "standalone": ["topic che non ha sinonimi ma è significativo"],
  "suggested_themes": [
    {{
      "theme": "nome del tema",
      "rationale": "perché questi topic appartengono allo stesso tema",
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
            print(f"✓  {n_groups} gruppi, {n_themes} temi")
        except Exception as e:
            print(f"✗  {e}")
            all_clusters.append({"error": str(e), "batch": batch_idx})

    return all_clusters


def analyze_interaction_types(raw_types: list) -> dict:
    """Raggruppa i tipi di interazione descritti liberamente nella Fase 1."""
    # Deduplica preservando frequenza
    type_freq = Counter(t.strip().lower() for t in raw_types if t.strip())
    top_types = [f"{t} ({c}x)" for t, c in type_freq.most_common(80)]

    prompt = f"""Ecco descrizioni dei tipi di interazione in un corpus di conversazioni:

{chr(10).join(top_types)}

COMPITO:
Raggruppa queste descrizioni in categorie di interazione coerenti.
Le categorie devono emergere dai dati, non essere inventate.

Restituisci SOLO un JSON:
{{
  "interaction_categories": [
    {{
      "canonical_name": "nome breve e chiaro",
      "description": "quando si applica questa categoria",
      "examples": ["esempio1", "esempio2"],
      "frequency_estimate": "alta/media/bassa"
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
    except Exception as e:
        return {"error": str(e), "raw_top": top_types[:20]}


def generate_readable_report(stats: dict, clusters: list, interactions: dict) -> str:
    """Genera un documento markdown leggibile per la revisione umana."""
    lines = [
        "# ANALISI DEL CORPUS — Fase 2",
        "",
        "> Questo documento serve come base per costruire la tassonomia (Fase 3).",
        "> Leggilo prima di eseguire fase3_taxonomy.py.",
        "",
        "---",
        "",
        "## 📊 Statistiche generali",
        "",
    ]

    lang_dist = stats.get("language_distribution", {})
    lines.append(f"**Lingue rilevate:**")
    for lang, count in list(lang_dist.items())[:10]:
        lines.append(f"- {lang}: {count} conversazioni")

    lines += ["", f"**Multi-topic:** {stats.get('multi_topic_count', 0)} conversazioni toccano argomenti molto diversi", ""]

    # Top topics
    lines += ["", "## 🏷️ Top 50 topics (frequenza grezza)", ""]
    for topic, count in list(stats["topic_frequencies"].items())[:50]:
        bar = "█" * min(count, 30)
        lines.append(f"- `{topic}` — {count}x  {bar}")

    # Top entità
    lines += ["", "## 🔧 Top 30 entità specifiche", ""]
    for entity, count in list(stats["entity_frequencies"].items())[:30]:
        lines.append(f"- **{entity}** — {count}x")

    # Tag esistenti
    lines += ["", "## 🔖 Tag già presenti (da Open WebUI)", ""]
    for tag, count in list(stats["existing_tag_frequencies"].items())[:40]:
        lines.append(f"- `{tag}` — {count}x")

    # Cluster
    lines += ["", "## 🗂️ Cluster tematici suggeriti dall'LLM", ""]
    for i, batch in enumerate(clusters):
        if "error" in batch:
            lines.append(f"- ⚠️ Batch {i+1}: errore — {batch['error']}")
            continue
        themes = batch.get("suggested_themes", [])
        for theme in themes:
            lines.append(f"### {theme.get('theme', '?')}")
            lines.append(f"*{theme.get('rationale', '')}*")
            topics_list = theme.get('canonical_topics', [])
            for t in topics_list:
                lines.append(f"- {t}")
            lines.append("")

    # Tipi di interazione
    lines += ["", "## 💬 Tipi di interazione", ""]
    for cat in interactions.get("interaction_categories", []):
        lines.append(f"### {cat.get('canonical_name', '?')} ({cat.get('frequency_estimate', '?')})")
        lines.append(f"{cat.get('description', '')}")
        examples = cat.get("examples", [])
        if examples:
            lines.append(f"*Es: {', '.join(examples[:3])}*")
        lines.append("")

    lines += [
        "---",
        "",
        "## ➡️ Prossimo passo",
        "",
        "Esegui `python fase3_taxonomy.py` per generare la tassonomia proposta.",
        "Poi **revisiona** `RIVEDI_TASSONOMIA.md` prima di procedere.",
    ]

    return "\n".join(lines)


def run():
    print_header("FASE 2 — Analisi del corpus")

    if output_exists("fase2_analysis.json", force=is_force()):
        sys.exit(0)

    model = resolve_model()
    print(f"Modello: {model}")

    fase1 = load_json(Path(OUTPUT_DIR) / "fase1_extracted.json")
    results = fase1["results"]
    ok_results = [r for r in results if r.get("status") == "ok"]

    print(f"Conversazioni valide: {len(ok_results)}/{len(results)}")

    # Step 1: statistiche grezze (istantanea, no LLM)
    print("\n[1/3] Raccolta statistiche grezze...")
    stats = collect_statistics(results)
    print(f"  Topics unici:   {len(stats['topic_frequencies'])}")
    print(f"  Entità uniche:  {len(stats['entity_frequencies'])}")
    print(f"  Lingue:         {list(stats['language_distribution'].keys())[:5]}")

    # Step 2: clustering dei topics
    print("\n[2/3] Clustering dei topics con LLM...")
    clusters = cluster_topics(stats["topic_frequencies"])

    # Step 3: analisi tipi di interazione
    print("\n[3/3] Analisi tipi di interazione...")
    interactions = analyze_interaction_types(stats["interaction_types_raw"])
    n_int_cats = len(interactions.get("interaction_categories", []))
    print(f"  Categorie di interazione trovate: {n_int_cats}")

    # Salva output strutturato
    output = {
        "metadata": {
            "fase": 2,
            "valid_results": len(ok_results),
            "unique_topics": len(stats["topic_frequencies"]),
            "unique_entities": len(stats["entity_frequencies"]),
            "generated_at": datetime.now().isoformat(),
        },
        "statistics": stats,
        "topic_clusters": clusters,
        "interaction_analysis": interactions,
    }

    out_path = Path(OUTPUT_DIR) / "fase2_analysis.json"
    save_json(output, out_path)

    # Genera report leggibile
    report = generate_readable_report(stats, clusters, interactions)
    report_path = Path(OUTPUT_DIR) / "fase2_readable.md"
    report_path.write_text(report, encoding="utf-8")

    print(f"\n✓ Fase 2 completata")
    print(f"  → Output:  {out_path}")
    print(f"  → Leggile: {report_path}")
    print(f"\n  Prossimo passo: python fase3_taxonomy.py")


if __name__ == "__main__":
    run()
