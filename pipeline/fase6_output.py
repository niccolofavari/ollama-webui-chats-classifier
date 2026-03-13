"""
FASE 6 — Output finale
═══════════════════════════════════════════════════════════════════════════════
Input:  ../output/fase5_validated.json
        ../output/fase0_chats.json
        ../chat-export-*.json  (originale per reimportazione OWU)
        ../output/fase3_taxonomy.json

Output (scegli quale generare):
  A) OUTPUT_openwebui_import.json   → reimporta in Open WebUI con tag
  B) OUTPUT_obsidian_vault/         → vault Obsidian con frontmatter YAML
  C) OUTPUT_catalog.csv             → spreadsheet
  D) OUTPUT_catalog.json            → indice JSON leggero (senza full_text)

Uso:
  python fase6_output.py           → genera tutti gli output
  python fase6_output.py openwebui → solo A
  python fase6_output.py obsidian  → solo B
  python fase6_output.py csv       → solo C
  python fase6_output.py json      → solo D
═══════════════════════════════════════════════════════════════════════════════
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import csv
import json
from datetime import datetime
from collections import defaultdict
from config import EXPORT_FILE, OUTPUT_DIR
from utils import load_json, save_json, print_header, is_force


def output_openwebui(classified: list, original_export: list, taxonomy: dict) -> Path:
    """
    Genera un JSON reimportabile in Open WebUI.
    Inietta i tag classificati in meta.tags + aggiunge tag categoria/sottocategoria.
    """
    class_lookup = {c["id"]: c for c in classified}

    for chat in original_export:
        chat_id = chat.get("id", "")
        if chat_id not in class_lookup:
            continue

        meta = class_lookup[chat_id]

        # Tag classificati
        new_tags = list(meta.get("tags", []))

        # Aggiungi categoria e sottocategoria come tag con prefisso
        macro = meta.get("macro_category")
        sub   = meta.get("subcategory")
        if macro:
            new_tags.append(f"cat:{macro}")
        if sub:
            new_tags.append(f"sub:{sub}")

        # Inietta in meta.tags (formato stringa, come già usato da OWU)
        existing_meta = chat.get("meta", {})
        existing_meta["tags"] = new_tags
        chat["meta"] = existing_meta

    out_path = Path(OUTPUT_DIR) / "OUTPUT_openwebui_import.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(original_export, f, indent=2, ensure_ascii=False)

    return out_path


def output_obsidian(classified: list, chats_lookup: dict, taxonomy: dict) -> Path:
    """Genera un vault Obsidian con un file .md per ogni conversazione."""
    vault = Path(OUTPUT_DIR) / "OUTPUT_obsidian_vault"
    vault.mkdir(parents=True, exist_ok=True)

    # Ottieni i metadati delle categorie per il frontmatter
    cat_meta = {
        c["id"]: c.get("name", c["id"])
        for c in taxonomy.get("macro_categories", [])
    }

    # Genera un index per categoria
    by_category = defaultdict(list)

    for item in classified:
        if item.get("macro_category", "").startswith("_"):
            continue  # salta errori

        cat_id  = item.get("macro_category", "altro")
        sub_id  = item.get("subcategory") or "_generale"
        cat_name = cat_meta.get(cat_id, cat_id)

        dest_dir = vault / cat_id / sub_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Recupera il testo della conversazione
        chat_data = chats_lookup.get(item["id"], {})
        full_text = chat_data.get("full_text", "[testo non disponibile]")

        # Frontmatter YAML
        tags_yaml = "\n".join(f"  - {t}" for t in item.get("tags", []))
        if not tags_yaml:
            tags_yaml = "  []"

        date = item.get("date", "unknown")
        title = item.get("title", "Senza titolo").replace('"', '\\"')
        models = ", ".join(chat_data.get("models", ["?"]))

        content = (
            f"---\n"
            f"title: \"{title}\"\n"
            f"date: {date}\n"
            f"category: {cat_id}\n"
            f"category_name: {cat_name}\n"
            f"subcategory: {sub_id}\n"
            f"interaction_type: {item.get('interaction_type', 'unknown')}\n"
            f"confidence: {item.get('confidence', 'unknown')}\n"
            f"models: {models}\n"
            f"n_messages: {chat_data.get('n_messages', 0)}\n"
            f"tags:\n{tags_yaml}\n"
            f"---\n\n"
            f"{full_text}\n"
        )

        # Nome file sicuro
        safe_title = "".join(
            c if c.isalnum() or c in " -_." else "_"
            for c in item.get("title", "untitled")
        )[:70].strip()
        filename = f"{date}_{safe_title}.md"

        (dest_dir / filename).write_text(content, encoding="utf-8")
        by_category[cat_id].append((date, safe_title, sub_id, item.get("tags", [])))

    # Genera indice globale
    index_lines = ["# Indice conversazioni", "", f"*Generato il {datetime.now().strftime('%Y-%m-%d')}*", ""]
    for cat_id, items in sorted(by_category.items()):
        cat_name = cat_meta.get(cat_id, cat_id)
        index_lines.append(f"\n## {cat_name} ({len(items)})")
        for date, title, sub, tags in sorted(items):
            tag_str = " ".join(f"`{t}`" for t in tags[:3])
            index_lines.append(f"- [[{cat_id}/{sub}/{date}_{title}|{title}]] {tag_str}")

    (vault / "INDEX.md").write_text("\n".join(index_lines), encoding="utf-8")

    return vault


def output_csv(classified: list) -> Path:
    """Genera un CSV tabellare con tutte le classificazioni."""
    out_path = Path(OUTPUT_DIR) / "OUTPUT_catalog.csv"

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "ID", "Titolo", "Data",
            "Categoria", "Sotto-categoria",
            "Tags", "Tipo Interazione",
            "Confidenza", "Note Ambiguità",
        ])
        for c in classified:
            writer.writerow([
                c.get("id", "")[:8],
                c.get("title", ""),
                c.get("date", ""),
                c.get("macro_category", ""),
                c.get("subcategory", "") or "",
                "; ".join(c.get("tags", [])),
                c.get("interaction_type", ""),
                c.get("confidence", ""),
                c.get("ambiguity_note", "") or "",
            ])

    return out_path


def output_json_catalog(classified: list, chats_lookup: dict) -> Path:
    """Genera un indice JSON leggero (senza full_text, solo metadati)."""
    catalog = []
    for c in classified:
        chat_data = chats_lookup.get(c["id"], {})
        catalog.append({
            "id":               c["id"],
            "title":            c.get("title", ""),
            "date":             c.get("date", ""),
            "macro_category":   c.get("macro_category", ""),
            "subcategory":      c.get("subcategory"),
            "tags":             c.get("tags", []),
            "interaction_type": c.get("interaction_type"),
            "confidence":       c.get("confidence"),
            "models":           chat_data.get("models", []),
            "n_messages":       chat_data.get("n_messages", 0),
            "char_count":       chat_data.get("char_count", 0),
        })

    out_path = Path(OUTPUT_DIR) / "OUTPUT_catalog.json"
    save_json(catalog, out_path)
    return out_path


def output_folder_checklist(classified: list, chats_lookup: dict, taxonomy: dict) -> Path:
    """
    Genera una checklist markdown per organizzare manualmente le chat in cartelle
    su Open WebUI dopo l'importazione.

    Struttura:
    - Una sezione per ogni macro_categoria (= cartella suggerita)
    - Dentro ogni sezione, sotto-sezioni per subcategory (= sotto-cartella)
    - Ogni chat elencata con titolo, data, confidenza e checkbox
    - Nota sulle chat che avevano già una cartella (folder_id presente)
    """
    cat_meta = {
        c["id"]: c.get("name", c["id"])
        for c in taxonomy.get("macro_categories", [])
    }
    sub_meta = {}
    for c in taxonomy.get("macro_categories", []):
        for s in c.get("subcategories", []):
            sub_meta[s["id"]] = s.get("name", s["id"])

    # Raggruppa per categoria → sottocategoria
    by_cat = defaultdict(lambda: defaultdict(list))
    errors = []

    for item in classified:
        macro = item.get("macro_category", "")
        if macro.startswith("_"):
            errors.append(item)
            continue
        sub = item.get("subcategory") or "_generale"
        chat_data = chats_lookup.get(item["id"], {})
        by_cat[macro][sub].append({
            "title":      item.get("title", "Senza titolo"),
            "date":       item.get("date", "?"),
            "confidence": item.get("confidence", "?"),
            "tags":       item.get("tags", []),
            "had_folder": bool(chat_data.get("folder_id")),  # aveva già una cartella?
            "id":         item.get("id", "")[:8],
        })

    # Statistiche rapide
    total_ok = sum(
        len(chats)
        for subs in by_cat.values()
        for chats in subs.values()
    )
    total_had_folder = sum(
        1
        for subs in by_cat.values()
        for chats in subs.values()
        for c in chats
        if c["had_folder"]
    )

    lines = [
        "# Checklist cartelle Open WebUI",
        "",
        "> **Come usarla:**",
        "> 1. Importa `OUTPUT_openwebui_import.json` in Open WebUI",
        "> 2. Crea le cartelle elencate qui sotto (una per macro-categoria)",
        "> 3. Per ogni sezione, seleziona le chat e spostale nella cartella",
        "> 4. Spunta la checkbox quando hai spostato ogni chat",
        "> 5. Le sotto-categorie puoi ignorarle o creare sotto-cartelle a tua scelta",
        "",
        f"> **Totale chat:** {total_ok}  |  "
        f"**Già in cartella (UUID preservato):** {total_had_folder}  |  "
        f"**Errori classificazione:** {len(errors)}",
        "",
        "---",
        "",
    ]

    for macro_id, subs in sorted(by_cat.items()):
        cat_name = cat_meta.get(macro_id, macro_id)
        total_in_cat = sum(len(v) for v in subs.values())

        lines.append(f"## 📁 {cat_name} ({total_in_cat} chat)")
        lines.append(f"*Crea la cartella: **\"{cat_name}\"***")
        lines.append("")

        for sub_id, chats in sorted(subs.items()):
            if sub_id == "_generale":
                sub_label = "Generale"
            else:
                sub_label = sub_meta.get(sub_id, sub_id)

            lines.append(f"### {sub_label} ({len(chats)})")

            # Ordina per data
            for chat in sorted(chats, key=lambda x: x["date"]):
                conf_icon = {"alta": "✅", "media": "🟡", "bassa": "🔴"}.get(
                    chat["confidence"], "⬜"
                )
                folder_note = " *(aveva cartella)*" if chat["had_folder"] else ""
                tags_str = " ".join(f"`{t}`" for t in chat["tags"][:3])
                lines.append(
                    f"- [ ] **{chat['title']}**{folder_note}  "
                    f"{conf_icon} {chat['date']}  {tags_str}"
                )

            lines.append("")

    # Sezione errori (se esistono)
    if errors:
        lines += [
            "---",
            "",
            f"## ⚠️ Chat non classificate ({len(errors)})",
            "",
            "Queste chat hanno avuto errori durante la classificazione.",
            "Dovrai assegnarle manualmente.",
            "",
        ]
        for e in errors:
            chat_data = chats_lookup.get(e["id"], {})
            lines.append(f"- [ ] **{e.get('title', '?')}** — {e.get('_error', 'errore sconosciuto')}")

    lines += [
        "",
        "---",
        "",
        "## 📊 Riepilogo",
        "",
        "| Cartella | Chat | Sotto-categorie |",
        "|----------|------|-----------------|",
    ]
    for macro_id, subs in sorted(by_cat.items()):
        cat_name = cat_meta.get(macro_id, macro_id)
        total_in_cat = sum(len(v) for v in subs.values())
        n_subs = len([s for s in subs if s != "_generale"])
        lines.append(f"| {cat_name} | {total_in_cat} | {n_subs} |")

    out_path = Path(OUTPUT_DIR) / "OUTPUT_folder_checklist.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def run():
    modes_arg = sys.argv[1:] if len(sys.argv) > 1 else ["all"]
    mode = modes_arg[0].lower()

    print_header("FASE 6 — Output finale")

    # Carica tutti i dati necessari
    validated = load_json(Path(OUTPUT_DIR) / "fase5_validated.json")
    classified = validated["classified"]

    fase0 = load_json(Path(OUTPUT_DIR) / "fase0_chats.json")
    chats_lookup = {c["id"]: c for c in fase0["chats"]}

    tax_obj = load_json(Path(OUTPUT_DIR) / "fase3_taxonomy.json")
    taxonomy = tax_obj["taxonomy"]

    export_path = Path(EXPORT_FILE)
    if not export_path.exists():
        export_path = Path("..") / EXPORT_FILE

    ok_classified = [
        c for c in classified
        if not c.get("macro_category", "").startswith("_")
    ]
    print(f"Conversazioni da esportare: {len(ok_classified)}/{len(classified)}")

    # ── Output A: Open WebUI ─────────────────────────────────────────────────
    if mode in ("all", "openwebui"):
        print("\n[A] Generazione Open WebUI import...", end=" ", flush=True)
        if export_path.exists():
            original = load_json(export_path)
            path = output_openwebui(classified, original, taxonomy)
            print(f"✓  {path}")
        else:
            print(f"✗  File originale non trovato: {export_path}")

    # ── Output B: Obsidian ───────────────────────────────────────────────────
    if mode in ("all", "obsidian"):
        print("\n[B] Generazione vault Obsidian...", end=" ", flush=True)
        path = output_obsidian(ok_classified, chats_lookup, taxonomy)
        n_files = sum(1 for _ in path.rglob("*.md"))
        print(f"✓  {path}  ({n_files} file)")

    # ── Output C: CSV ────────────────────────────────────────────────────────
    if mode in ("all", "csv"):
        print("\n[C] Generazione CSV...", end=" ", flush=True)
        path = output_csv(classified)
        print(f"✓  {path}")

    # ── Output D: JSON catalog ───────────────────────────────────────────────
    if mode in ("all", "json"):
        print("\n[D] Generazione catalogo JSON...", end=" ", flush=True)
        path = output_json_catalog(ok_classified, chats_lookup)
        print(f"✓  {path}")

    # ── Checklist cartelle (sempre generata) ────────────────────────────────
    print("\n[E] Generazione checklist cartelle...", end=" ", flush=True)
    path = output_folder_checklist(ok_classified, chats_lookup, taxonomy)
    print(f"✓  {path}")

    print(f"\n✓ Fase 6 completata. Tutti i file sono in {OUTPUT_DIR}/")


if __name__ == "__main__":
    run()
