"""
FASE 4 — Classificazione vincolata
═══════════════════════════════════════════════════════════════════════════════
Input:  ../output/fase0_chats.json
        ../output/fase1_extracted.json
        ../output/fase3_taxonomy.json   ← deve avere "approved": true
Output: ../output/fase4_classified.json

Cosa fa:
- Usa la tassonomia APPROVATA come vocabolario rigido
- Combina il testo originale con l'estrazione della Fase 1 (più efficiente)
- Valida che le categorie e i tag restituiti siano tra quelli ammessi
- Registra la confidenza e le ambiguità per la Fase 5 (QA)
- Checkpoint anti-crash ogni N chat
═══════════════════════════════════════════════════════════════════════════════
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import json
from datetime import datetime
from collections import Counter
from config import (
    OUTPUT_DIR, CHECKPOINT_DIR, CHECKPOINT_EVERY,
    LLM_OPTIONS_CLASSIFY,
)
from utils import (
    load_json, save_json, save_checkpoint, load_checkpoint, clear_checkpoint,
    truncate_smart, llm_call_json, print_header, output_exists, is_force, resolve_model
)


def build_classification_system(taxonomy: dict) -> tuple[str, list, list, list]:
    """
    Costruisce il system prompt di classificazione dalla tassonomia approvata.
    Restituisce (system_prompt, valid_cat_ids, valid_tag_slugs, valid_int_ids).
    """
    cats = taxonomy.get("macro_categories", [])
    tags = taxonomy.get("controlled_tags", [])
    int_types = taxonomy.get("interaction_types", [])

    # Costruisci lista categorie con criteri
    cat_lines = []
    valid_cat_ids = []
    for cat in cats:
        cat_id = cat["id"]
        valid_cat_ids.append(cat_id)
        subs = cat.get("subcategories", [])
        sub_ids = [s["id"] for s in subs]
        sub_str = ", ".join(sub_ids) if sub_ids else "nessuna"
        cat_lines.append(
            f"- **{cat_id}** ({cat['name']}): {cat['description']}\n"
            f"  Sotto-categorie valide: {sub_str}"
        )

    # Lista tag validi
    valid_tag_slugs = [t["tag"] for t in tags]
    tag_lines = [f"  {t['tag']}: {t['description']}" for t in tags]

    # Tipi di interazione validi
    valid_int_ids = [i["id"] for i in int_types]
    int_lines = [f"  {i['id']}: {i['description']}" for i in int_types]

    # Regole di classificazione (se presenti)
    rules = taxonomy.get("classification_rules", [])
    rules_str = "\n".join(f"  {r}" for r in rules) if rules else ""

    system = f"""Sei un classificatore preciso. Classifica la conversazione usando 
ESCLUSIVAMENTE i valori elencati qui sotto.

MACRO-CATEGORIE AMMESSE:
{chr(10).join(cat_lines)}

TAG AMMESSI (scegli 3-6 tra questi, solo quelli pertinenti):
{chr(10).join(tag_lines)}

TIPI DI INTERAZIONE AMMESSI:
{chr(10).join(int_lines)}

{"REGOLE:" + chr(10) + rules_str if rules_str else ""}

Restituisci SOLO un JSON:
{{
  "macro_category": "uno degli id ammessi",
  "subcategory": "id di una sotto-categoria valida per questa categoria, o null",
  "tags": ["tag1", "tag2", "tag3"],
  "interaction_type": "uno degli id ammessi",
  "confidence": "alta|media|bassa",
  "ambiguity_note": "solo se confidence è bassa: spiega il dubbio; altrimenti null"
}}

⚠️ OBBLIGATORIO: usa solo valori esattamente come scritti nelle liste sopra.
Se hai dubbi tra due categorie, scegli la più specifica e metti confidence "media"."""

    return system, valid_cat_ids, valid_tag_slugs, valid_int_ids


def classify_single(
    chat: dict,
    fase1_data: dict | None,
    system_prompt: str,
    valid_cat_ids: list,
    valid_tag_slugs: list,
    valid_int_ids: list,
) -> dict:
    """Classifica una singola conversazione e valida l'output."""

    # Costruisci il prompt combinando testo originale + estrazione fase 1
    text = truncate_smart(chat["full_text"], max_chars=4000)

    fase1_ctx = ""
    if fase1_data:
        topics_str   = ", ".join(fase1_data.get("topics", [])[:10])
        entities_str = ", ".join(fase1_data.get("entities", [])[:10])
        fase1_ctx = (
            f"\n\n[ANALISI PRECEDENTE]\n"
            f"Riassunto: {fase1_data.get('summary', '')}\n"
            f"Topics estratti: {topics_str}\n"
            f"Entità citate: {entities_str}\n"
            f"Intento utente: {fase1_data.get('user_intent', '')}"
        )

    prompt = (
        f"Titolo: {chat['title']}\n"
        f"Data: {chat['date']}\n"
        f"Modello AI usato: {', '.join(chat.get('models', ['?']))}\n"
        f"{fase1_ctx}\n\n"
        f"CONVERSAZIONE:\n\n{text}\n\n"
        f"Classifica questa conversazione."
    )

    result = llm_call_json(
        prompt=prompt,
        system=system_prompt,
        options=LLM_OPTIONS_CLASSIFY,
        required_fields=["macro_category", "tags", "interaction_type", "confidence"],
        timeout=120,
    )

    # ── Validazione ──────────────────────────────────────────────────────────

    # Macro-categoria
    macro = result.get("macro_category", "")
    if macro not in valid_cat_ids:
        # Cerca una corrispondenza parziale (fallback soft)
        match = next((v for v in valid_cat_ids if v in macro or macro in v), None)
        if match:
            result["macro_category"] = match
            result["_validation_note"] = f"categoria corretta da '{macro}' a '{match}'"
        else:
            result["macro_category"] = valid_cat_ids[-1]  # ultima = miscellanea
            result["_validation_note"] = f"categoria non valida '{macro}', assegnata miscellanea"
            result["confidence"] = "bassa"

    # Tag: filtra quelli non ammessi
    raw_tags = result.get("tags", [])
    valid_tags = [t for t in raw_tags if t in valid_tag_slugs]
    invalid_tags = [t for t in raw_tags if t not in valid_tag_slugs]
    result["tags"] = valid_tags
    if invalid_tags:
        result["_invalid_tags_dropped"] = invalid_tags

    # Interaction type
    int_type = result.get("interaction_type", "")
    if int_type not in valid_int_ids:
        result["interaction_type"] = valid_int_ids[0] if valid_int_ids else "other"
        result["_int_type_note"] = f"tipo non valido '{int_type}', usato fallback"

    return result


def run():
    print_header("FASE 4 — Classificazione vincolata")

    model = resolve_model()
    force = is_force()

    # Se l'output finale esiste già e non c'è --force, salta
    if not force and output_exists("fase4_classified.json"):
        sys.exit(0)

    # --force: cancella checkpoint precedente e riparte da zero
    if force:
        clear_checkpoint("fase4")
        print("⚠️  --force: checkpoint precedente cancellato, riparto da zero")

    # Verifica approvazione tassonomia
    tax_path = Path(OUTPUT_DIR) / "fase3_taxonomy.json"
    tax_obj = load_json(tax_path)

    if not tax_obj.get("approved"):
        print("❌ La tassonomia non è stata approvata!")
        print(f"   Apri {tax_path} e imposta \"approved\": true dopo aver revisionato.")
        sys.exit(1)

    taxonomy = tax_obj["taxonomy"]

    # Costruisci system prompt e vocabolari validi
    system_prompt, valid_cat_ids, valid_tag_slugs, valid_int_ids = \
        build_classification_system(taxonomy)

    print(f"Modello: {model}")
    print(f"Categorie valide: {valid_cat_ids}")
    print(f"Tag validi: {len(valid_tag_slugs)}")
    print(f"Tipi interazione: {valid_int_ids}")

    # Carica dati
    fase0 = load_json(Path(OUTPUT_DIR) / "fase0_chats.json")
    fase1 = load_json(Path(OUTPUT_DIR) / "fase1_extracted.json")

    chats = fase0["chats"]
    total = len(chats)

    # Lookup fase1 per ID
    fase1_lookup = {
        r["id"]: r.get("extraction", {})
        for r in fase1["results"]
        if r.get("status") == "ok"
    }

    # Resume da checkpoint
    classified = load_checkpoint("fase4") or []
    processed_ids = {c["id"] for c in classified}
    if processed_ids:
        print(f"\nRipresa dal checkpoint: {len(classified)}/{total} già classificate")

    errors = sum(1 for c in classified if c.get("_error"))

    print()
    for i, chat in enumerate(chats):
        if chat["id"] in processed_ids:
            continue

        n_done = len(classified)
        pct = n_done / total * 100
        print(f"[{n_done+1:3d}/{total}] {pct:4.0f}%  {chat['title'][:50]:<50}", end=" ", flush=True)

        fase1_data = fase1_lookup.get(chat["id"])

        try:
            result = classify_single(
                chat, fase1_data,
                system_prompt, valid_cat_ids, valid_tag_slugs, valid_int_ids,
            )

            conf_icon = {"alta": "✓", "media": "~", "bassa": "?"}.get(
                result.get("confidence", ""), "?"
            )
            cat = result.get("macro_category", "?")
            sub = result.get("subcategory") or ""
            sub_str = f"/{sub}" if sub else ""
            print(f"{conf_icon} → {cat}{sub_str}")

            classified.append({
                "id":    chat["id"],
                "title": chat["title"],
                "date":  chat["date"],
                **result,
            })

        except Exception as e:
            errors += 1
            print(f"✗ ERRORE: {e}")
            classified.append({
                "id":             chat["id"],
                "title":          chat["title"],
                "date":           chat["date"],
                "macro_category": "_ERRORE",
                "tags":           [],
                "confidence":     "nulla",
                "_error":         str(e),
            })

        # Checkpoint
        if len(classified) % CHECKPOINT_EVERY == 0:
            save_checkpoint(classified, "fase4")

    # Statistiche finali
    cat_dist = Counter(c.get("macro_category", "?") for c in classified)
    conf_dist = Counter(c.get("confidence", "?") for c in classified)

    output = {
        "metadata": {
            "fase": 4,
            "total": len(classified),
            "errors": errors,
            "model": model,
            "category_distribution": dict(cat_dist.most_common()),
            "confidence_distribution": dict(conf_dist),
            "generated_at": datetime.now().isoformat(),
        },
        "classified": classified,
    }

    out_path = Path(OUTPUT_DIR) / "fase4_classified.json"
    save_json(output, out_path)
    clear_checkpoint("fase4")

    print(f"\n✓ Fase 4 completata: {len(classified)} classificate, {errors} errori")
    print(f"\n  Distribuzione categorie:")
    total_c = len(classified)
    for cat, count in cat_dist.most_common():
        bar = "█" * int(count / total_c * 40)
        pct = count / total_c * 100
        print(f"    {cat:<30} {count:4d} ({pct:4.0f}%)  {bar}")

    low_conf = sum(1 for c in classified if c.get("confidence") == "bassa")
    if low_conf:
        print(f"\n  ⚠ {low_conf} conversazioni a bassa confidenza → revisiona in Fase 5")

    print(f"\n  → Output: {out_path}")
    print(f"\n  Prossimo passo: python fase5_qa.py")


if __name__ == "__main__":
    run()
