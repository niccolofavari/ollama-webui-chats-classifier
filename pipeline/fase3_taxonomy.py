"""
FASE 3 — Costruzione della tassonomia
═══════════════════════════════════════════════════════════════════════════════
Input:  ../output/fase2_analysis.json
Output: ../output/fase3_taxonomy.json    ← ⚠️ DA RIVEDERE MANUALMENTE
        ../output/RIVEDI_TASSONOMIA.md   ← versione leggibile

Cosa fa:
- L'LLM propone una tassonomia basata SOLO sui pattern emersi dalla Fase 2
- Genera un file markdown per la revisione umana
- Il file JSON ha un flag "approved: false" che DEVI cambiare in true
  dopo aver revisionato e approvato (o modificato) la tassonomia

⚠️  NON eseguire la Fase 4 senza aver approvato questo file.
═══════════════════════════════════════════════════════════════════════════════
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import json
from datetime import datetime
from config import OUTPUT_DIR, LLM_OPTIONS_TAXONOMY
from utils import load_json, save_json, llm_call_json, print_header, print_action_required, is_force, resolve_model


def build_context_for_llm(analysis: dict) -> str:
    """Costruisce il contesto riassuntivo da passare all'LLM."""
    stats = analysis.get("statistics", {})

    # Top 60 topics
    top_topics = list(stats.get("topic_frequencies", {}).items())[:60]
    topics_str = "\n".join(f"  - {t} ({c}x)" for t, c in top_topics)

    # Top 30 entità
    top_entities = list(stats.get("entity_frequencies", {}).items())[:30]
    entities_str = "\n".join(f"  - {e} ({c}x)" for e, c in top_entities)

    # Tag esistenti (già assegnati da OWU)
    top_existing = list(stats.get("existing_tag_frequencies", {}).items())[:40]
    existing_str = "\n".join(f"  - {t} ({c}x)" for t, c in top_existing)

    # Temi suggeriti dai cluster
    clusters = analysis.get("topic_clusters", [])
    themes_parts = []
    for batch in clusters:
        for theme in batch.get("suggested_themes", []):
            name = theme.get("theme", "?")
            rationale = theme.get("rationale", "")
            topics_list = ", ".join(theme.get("canonical_topics", [])[:5])
            themes_parts.append(f"  - **{name}**: {rationale} (es: {topics_list})")
    themes_str = "\n".join(themes_parts) if themes_parts else "  (nessun tema suggerito)"

    # Tipi di interazione
    int_cats = analysis.get("interaction_analysis", {}).get("interaction_categories", [])
    int_str = "\n".join(
        f"  - {c.get('canonical_name', '?')}: {c.get('description', '')}"
        for c in int_cats
    )

    # Lingue
    lang_dist = stats.get("language_distribution", {})
    lang_str = ", ".join(f"{l} ({c})" for l, c in list(lang_dist.items())[:5])

    return f"""STATISTICHE DEL CORPUS:
- Lingue: {lang_str}
- Topics unici emersi: {len(stats.get('topic_frequencies', {}))}
- Conversazioni multi-topic: {stats.get('multi_topic_count', 0)}

TOP TOPICS (per frequenza):
{topics_str}

ENTITÀ SPECIFICHE PIÙ CITATE:
{entities_str}

TAG GIÀ ASSEGNATI DA OPEN WEBUI:
{existing_str}

TEMI SUGGERITI DAL CLUSTERING:
{themes_str}

TIPI DI INTERAZIONE RILEVATI:
{int_str}"""


def propose_taxonomy(context: str) -> dict:
    prompt = f"""Sei un bibliotecario digitale. Devi progettare una tassonomia per 
organizzare un archivio personale di conversazioni con AI.

Ecco l'analisi del corpus:

{context}

OBIETTIVO: proporre una tassonomia che:
1. Emerga DAI DATI (non inventare categorie assenti nel corpus)
2. Abbia 6-12 macro-categorie (gestibili mentalmente)
3. Ogni macro-categoria abbia sotto-categorie specifiche
4. Preveda una macro-categoria "Miscellanea" per gli outlier
5. Abbia un vocabolario controllato di tag (30-60 tag, precisi e non ridondanti)
6. Sia bilanciata: nessuna categoria deve contenere >40% delle conversazioni
7. I criteri di classificazione siano CHIARI e non ambigui

Restituisci SOLO un JSON:
{{
  "taxonomy_notes": "note sul corpus e scelte fatte",
  "macro_categories": [
    {{
      "id": "slug-lowercase",
      "name": "Nome Leggibile",
      "description": "Criteri precisi: una conversazione finisce qui quando...",
      "subcategories": [
        {{
          "id": "slug",
          "name": "Nome",
          "description": "criteri specifici",
          "example_entities": ["tool1", "tecnologia2"]
        }}
      ]
    }}
  ],
  "controlled_tags": [
    {{
      "tag": "tag-slug",
      "description": "cosa rappresenta esattamente",
      "merged_from": ["sinonimo1", "sinonimo2"]
    }}
  ],
  "interaction_types": [
    {{
      "id": "slug",
      "name": "Nome",
      "description": "criterio"
    }}
  ],
  "classification_rules": [
    "Regola 1: se la conversazione tratta X, va in categoria Y",
    "Regola 2: in caso di dubbio tra A e B, scegliere in base a..."
  ]
}}"""

    return llm_call_json(
        prompt=prompt,
        options=LLM_OPTIONS_TAXONOMY,
        required_fields=["macro_categories", "controlled_tags"],
        timeout=360,
    )


def generate_readable_taxonomy(taxonomy: dict) -> str:
    lines = [
        "# TASSONOMIA PROPOSTA — DA RIVEDERE",
        "",
        "> **Istruzioni:**",
        "> 1. Leggi attentamente questa proposta",
        "> 2. Modifica `fase3_taxonomy.json` come preferisci",
        "> 3. Cambia `\"approved\": false` in `\"approved\": true`",
        "> 4. Solo allora esegui `python fase4_classify.py`",
        "",
        "---",
        "",
    ]

    notes = taxonomy.get("taxonomy_notes", "")
    if notes:
        lines += [f"## 💡 Note dell'LLM sul corpus", "", notes, ""]

    lines += ["## 🗂️ Macro-categorie", ""]
    for cat in taxonomy.get("macro_categories", []):
        lines.append(f"### `{cat.get('id', '?')}` — {cat.get('name', '?')}")
        lines.append(f"**Criteri:** {cat.get('description', '')}")
        lines.append("")
        subs = cat.get("subcategories", [])
        if subs:
            lines.append("**Sotto-categorie:**")
            for sub in subs:
                examples = sub.get("example_entities", [])
                ex_str = f" *(es: {', '.join(examples[:4])})*" if examples else ""
                lines.append(f"- `{sub.get('id', '?')}` — {sub.get('name', '?')}: {sub.get('description', '')}{ex_str}")
            lines.append("")

    lines += ["---", "", "## 🏷️ Vocabolario controllato dei tag", ""]
    for tag_obj in taxonomy.get("controlled_tags", []):
        merged = tag_obj.get("merged_from", [])
        merged_str = f" *(include: {', '.join(merged)})*" if merged else ""
        lines.append(f"- `{tag_obj.get('tag', '?')}` — {tag_obj.get('description', '')}{merged_str}")

    lines += ["", "---", "", "## 💬 Tipi di interazione", ""]
    for it in taxonomy.get("interaction_types", []):
        lines.append(f"- `{it.get('id', '?')}` — **{it.get('name', '?')}**: {it.get('description', '')}")

    rules = taxonomy.get("classification_rules", [])
    if rules:
        lines += ["", "---", "", "## 📋 Regole di classificazione", ""]
        for rule in rules:
            lines.append(f"- {rule}")

    return "\n".join(lines)


def run():
    print_header("FASE 3 — Costruzione tassonomia")

    force = is_force()
    tax_path = Path(OUTPUT_DIR) / "fase3_taxonomy.json"

    # Protezione critica: non sovrascrivere una tassonomia già approvata
    if tax_path.exists():
        existing = load_json(tax_path)
        if existing.get("approved") and not force:
            print(f"✅ Tassonomia già approvata — non la sovrascrivo.")
            print(f"   Se vuoi rigenerare da zero: python fase3_taxonomy.py --force")
            print(f"   ⚠️  --force resetterà 'approved: false' e dovrai riapprovare.")
            sys.exit(0)
        elif not existing.get("approved") and not force:
            print(f"⚠️  Esiste già una tassonomia NON approvata.")
            print(f"   → Per approvarla: modifica {tax_path} e metti \"approved\": true")
            print(f"   → Per rigenerarne una nuova: python fase3_taxonomy.py --force")
            sys.exit(0)
        elif force and existing.get("approved"):
            print(f"⚠️  --force: la tassonomia approvata verrà sovrascritta.")
            print(f"   Dovrai riapprovare prima di poter eseguire la Fase 4.")

    model = resolve_model()
    analysis = load_json(Path(OUTPUT_DIR) / "fase2_analysis.json")

    print(f"Modello: {model}")
    print("Costruisco il contesto dall'analisi del corpus...")
    context = build_context_for_llm(analysis)

    print("Chiedo all'LLM di proporre la tassonomia...")
    taxonomy = propose_taxonomy(context)

    n_cats = len(taxonomy.get("macro_categories", []))
    n_tags = len(taxonomy.get("controlled_tags", []))
    n_int  = len(taxonomy.get("interaction_types", []))
    print(f"  Macro-categorie: {n_cats}")
    print(f"  Tag controllati: {n_tags}")
    print(f"  Tipi interazione: {n_int}")

    # Salva JSON (con approved: false)
    output = {
        "metadata": {
            "fase": 3,
            "generated_at": datetime.now().isoformat(),
            "model": model,
            "instructions": [
                "1. Leggi RIVEDI_TASSONOMIA.md nella cartella output/",
                "2. Modifica questo file se necessario",
                "3. Cambia 'approved' da false a true",
                "4. Esegui pipeline/fase4_classify.py",
            ],
        },
        "approved": False,
        "taxonomy": taxonomy,
    }

    save_json(output, tax_path)

    # Salva versione leggibile
    readable = generate_readable_taxonomy(taxonomy)
    readable_path = Path(OUTPUT_DIR) / "RIVEDI_TASSONOMIA.md"
    readable_path.write_text(readable, encoding="utf-8")

    print(f"\n✓ Fase 3 completata")
    print(f"  → JSON:    {tax_path}")
    print(f"  → Leggile: {readable_path}")

    print_action_required([
        "1. Leggi output/RIVEDI_TASSONOMIA.md",
        "2. Modifica output/fase3_taxonomy.json",
        "3. Imposta \"approved\": true nel JSON",
        "4. Poi: python fase4_classify.py",
    ])


if __name__ == "__main__":
    run()
