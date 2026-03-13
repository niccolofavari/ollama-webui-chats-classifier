"""
FASE 1 — Estrazione libera
═══════════════════════════════════════════════════════════════════════════════
Input:  ../output/fase0_chats.json
Output: ../output/fase1_extracted.json

Cosa fa:
- Per ogni conversazione chiede all'LLM di descrivere LIBERAMENTE il contenuto
- NESSUNA categoria predefinita — le parole vengono dall'LLM, non da noi
- Usa i tag esistenti (meta.tags) come contesto aggiuntivo, NON come vincolo
- Salva checkpoint ogni N chat (riprende da dove si era fermato se crasha)
═══════════════════════════════════════════════════════════════════════════════
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime
from config import OUTPUT_DIR, CHECKPOINT_DIR, CHECKPOINT_EVERY, LLM_OPTIONS_EXTRACT
from utils import (
    load_json, save_json, save_checkpoint, load_checkpoint, clear_checkpoint,
    truncate_smart, llm_call_json, print_header, output_exists, is_force, resolve_model
)


# ⚠️  PROMPT VOLUTAMENTE APERTO — zero suggerimenti tematici
SYSTEM_PROMPT = """Sei un archivista. Analizza la conversazione e descrivine il contenuto con parole tue.

Restituisci SOLO un JSON valido, nessun altro testo:
{
  "summary": "1-2 frasi che descrivono di cosa tratta la conversazione",
  "topics": ["argomento libero 1", "argomento libero 2", ...],
  "entities": ["nomi specifici di tool/tecnologie/concetti/persone/luoghi citati"],
  "user_intent": "cosa cercava di ottenere o capire l'utente",
  "interaction_type": "descrivi con parole tue il tipo di interazione (es: richiesta aiuto, debug, brainstorming, traduzione, spiegazione, ecc.)",
  "language": "lingua principale",
  "multi_topic": true o false (la conversazione tocca argomenti molto diversi tra loro?),
  "quality_note": "breve nota se la conversazione è troncata/confusa/incompleta, altrimenti null"
}

REGOLE IMPORTANTI:
- topics: usa le parole più naturali e specifiche, non categorie astratte
- entities: solo NOMI PROPRI di cose concrete menzionate nella conversazione
- Se la conversazione tocca più argomenti, elencali TUTTI nei topics
- Rispondi SOLO con il JSON, senza markdown, senza commenti"""


def extract_single(chat: dict) -> dict:
    """Estrae informazioni da una singola conversazione."""
    text = truncate_smart(chat["full_text"])

    # Includi i tag esistenti come contesto (non come vincolo)
    existing_tags_ctx = ""
    if chat.get("existing_tags"):
        tags_str = ", ".join(chat["existing_tags"])
        existing_tags_ctx = (
            f"\n\n[NOTA: questa conversazione aveva già i seguenti tag "
            f"assegnati automaticamente: {tags_str} — usali come contesto "
            f"ma non limitarti ad essi]"
        )

    prompt = (
        f"Titolo della conversazione: {chat['title']}\n"
        f"Data: {chat['date']}\n"
        f"Modello usato: {', '.join(chat.get('models', ['unknown']))}\n"
        f"{existing_tags_ctx}\n\n"
        f"CONVERSAZIONE:\n\n{text}"
    )

    return llm_call_json(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        options=LLM_OPTIONS_EXTRACT,
        required_fields=["summary", "topics", "entities", "user_intent"],
    )


def run():
    print_header("FASE 1 — Estrazione libera")

    model = resolve_model()
    force = is_force()

    # Se l'output finale esiste già e non c'è --force, salta
    if not force and output_exists("fase1_extracted.json"):
        sys.exit(0)

    fase0 = load_json(Path(OUTPUT_DIR) / "fase0_chats.json")
    chats = fase0["chats"]
    total = len(chats)

    print(f"Modello: {model}")
    print(f"Chat da processare: {total}")

    # --force: cancella checkpoint precedente e riparte da zero
    if force:
        clear_checkpoint("fase1")
        print("⚠️  --force: checkpoint precedente cancellato, riparto da zero")

    # Carica checkpoint se esiste (resume)
    results = load_checkpoint("fase1") or []
    processed_ids = {r["id"] for r in results}

    if processed_ids:
        print(f"Ripresa dal checkpoint: {len(results)}/{total} già processate")

    errors = sum(1 for r in results if r.get("status") == "error")

    for i, chat in enumerate(chats):
        if chat["id"] in processed_ids:
            continue

        n_done = len(results)
        pct = n_done / total * 100
        print(f"[{n_done+1:3d}/{total}] {pct:4.0f}%  {chat['title'][:55]:<55}", end=" ", flush=True)

        try:
            extracted = extract_single(chat)

            # Normalizzazione minima (no interpretazione, solo pulizia)
            extracted["topics"] = [
                t.strip().lower() for t in extracted.get("topics", []) if t.strip()
            ]
            extracted["entities"] = [
                e.strip() for e in extracted.get("entities", []) if e.strip()
            ]

            results.append({
                "id":            chat["id"],
                "title":         chat["title"],
                "date":          chat["date"],
                "char_count":    chat["char_count"],
                "n_messages":    chat["n_messages"],
                "existing_tags": chat.get("existing_tags", []),
                "status":        "ok",
                "extraction":    extracted,
            })
            n_topics = len(extracted.get("topics", []))
            print(f"✓  {n_topics} topics")

        except Exception as e:
            errors += 1
            results.append({
                "id":    chat["id"],
                "title": chat["title"],
                "date":  chat["date"],
                "status": "error",
                "error": str(e),
            })
            print(f"✗  ERRORE: {e}")

        # Checkpoint periodico
        if len(results) % CHECKPOINT_EVERY == 0:
            save_checkpoint(results, "fase1")

    # Output finale
    ok_count = sum(1 for r in results if r["status"] == "ok")
    output = {
        "metadata": {
            "fase": 1,
            "total": total,
            "ok": ok_count,
            "errors": errors,
            "model": model,
            "generated_at": datetime.now().isoformat(),
        },
        "results": results,
    }

    out_path = Path(OUTPUT_DIR) / "fase1_extracted.json"
    save_json(output, out_path)
    clear_checkpoint("fase1")

    print(f"\n✓ Fase 1 completata: {ok_count}/{total} ok, {errors} errori")
    print(f"  → Output: {out_path}")
    print(f"\n  Prossimo passo: python fase2_analyze.py")


if __name__ == "__main__":
    run()
