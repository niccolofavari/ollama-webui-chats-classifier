"""
FASE 0 — Split e normalizzazione
═══════════════════════════════════════════════════════════════════════════════
Input:  ../chat-export-*.json  (export da Open WebUI)
Output: ../output/fase0_chats.json

Cosa fa:
- Legge l'export di Open WebUI
- Linearizza la history (che è un grafo, non una lista)
- Estrae metadati oggettivi (date, conteggi, modelli usati)
- Conserva i tag già presenti in meta.tags (sono già 411/429!)
- NON interpreta il contenuto
═══════════════════════════════════════════════════════════════════════════════
"""

import sys
from pathlib import Path

# Aggiunge la cartella pipeline al path per gli import
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime
from collections import Counter
from config import EXPORT_FILE, OUTPUT_DIR
from utils import (
    load_json, save_json, linearize_messages, build_full_text,
    print_header, output_exists, is_force
)


def run():
    print_header("FASE 0 — Split e normalizzazione")

    if output_exists("fase0_chats.json", force=is_force()):
        sys.exit(0)

    export_path = Path(EXPORT_FILE)
    if not export_path.exists():
        # Prova nella directory padre
        export_path = Path("..") / EXPORT_FILE
    if not export_path.exists():
        print(f"❌ File non trovato: {EXPORT_FILE}")
        print(f"   Assicurati di avere il file nella directory del progetto.")
        sys.exit(1)

    print(f"Carico {export_path} ({export_path.stat().st_size / 1e6:.1f} MB)...")
    raw = load_json(export_path)

    chats = []
    skipped = 0

    for item in raw:
        # Linearizza i messaggi dal grafo
        messages = linearize_messages(item)

        if not messages:
            skipped += 1
            continue

        full_text = build_full_text(messages)

        if not full_text.strip():
            skipped += 1
            continue

        # Timestamp: Open WebUI usa secondi o millisecondi
        created_at = item.get("created_at", 0)
        updated_at = item.get("updated_at", 0)

        def ts_to_str(ts):
            if not ts:
                return "unknown"
            if ts > 1e10:
                ts = ts / 1000
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

        # Modelli usati in questa chat
        models = item.get("chat", {}).get("models", [])

        # Tag già presenti (da meta.tags — li preserviamo come "existing_tags")
        existing_tags = item.get("meta", {}).get("tags", [])

        # Conteggio messaggi per ruolo
        role_counts = Counter(m["role"] for m in messages)

        chats.append({
            "id":               item.get("id", ""),
            "title":            item.get("title", "Senza titolo"),
            "date":             ts_to_str(created_at),
            "date_updated":     ts_to_str(updated_at),
            "archived":         item.get("archived", False),
            "pinned":           item.get("pinned", False),
            "folder_id":        item.get("folder_id"),
            "models":           models,
            "n_user_messages":  role_counts.get("user", 0),
            "n_assistant_messages": role_counts.get("assistant", 0),
            "n_messages":       len(messages),
            "char_count":       len(full_text),
            "existing_tags":    existing_tags,   # tag già assegnati da OWU
            "full_text":        full_text,
        })

    # Statistiche
    total = len(chats)
    dates = [c["date"] for c in chats if c["date"] != "unknown"]
    dates.sort()
    char_counts = sorted(c["char_count"] for c in chats)
    mid = len(char_counts) // 2
    median_chars = char_counts[mid]
    has_existing_tags = sum(1 for c in chats if c["existing_tags"])

    output = {
        "metadata": {
            "fase": 0,
            "source_file": str(export_path.name),
            "total_chats": total,
            "skipped": skipped,
            "date_range": f"{dates[0]} → {dates[-1]}" if dates else "unknown",
            "chars_min": char_counts[0],
            "chars_median": median_chars,
            "chars_max": char_counts[-1],
            "chars_total": sum(char_counts),
            "chats_with_existing_tags": has_existing_tags,
            "generated_at": datetime.now().isoformat(),
        },
        "chats": chats,
    }

    out_path = Path(OUTPUT_DIR) / "fase0_chats.json"
    save_json(output, out_path)

    print(f"\n✓ {total} conversazioni estratte ({skipped} saltate)")
    print(f"  Date:        {output['metadata']['date_range']}")
    print(f"  Char/chat:   min={char_counts[0]:,}  median={median_chars:,}  max={char_counts[-1]:,}")
    print(f"  Totale testo: {sum(char_counts)/1e6:.1f} MB")
    print(f"  Con tag esistenti: {has_existing_tags}/{total}")
    print(f"\n  → Output: {out_path}")
    print(f"\n  Prossimo passo: python fase1_extract.py")


if __name__ == "__main__":
    run()
