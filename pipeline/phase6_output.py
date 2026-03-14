"""
Phase 6 — Final output
===============================================================================
Input:  output/phase5_validated.json
        output/phase0_chats.json
        ../chat-export-*.json  (original, for Open WebUI reimport)
        output/phase3_taxonomy.json

Output (choose which to generate):
  A) OUTPUT_openwebui_import.json  → reimport into Open WebUI with tags
  B) OUTPUT_obsidian_vault/        → Obsidian vault with YAML frontmatter
  C) OUTPUT_catalog.csv            → spreadsheet
  D) OUTPUT_catalog.json           → lightweight JSON index (no full text)
  E) OUTPUT_folder_checklist.md    → step-by-step checklist for OWU folders

Usage:
  python phase6_output.py           → generate all outputs
  python phase6_output.py openwebui → only A
  python phase6_output.py obsidian  → only B
  python phase6_output.py csv       → only C
  python phase6_output.py json      → only D
===============================================================================
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import csv
import json
from datetime import datetime
from collections import defaultdict

from config import EXPORT_FILE, OUTPUT_DIR
from logger import get_logger
from utils import load_json, save_json, print_header, is_force

log = get_logger("phase6")


# ── Output generators ─────────────────────────────────────────────────────────

def output_openwebui(classified: list, original_export: list, taxonomy: dict) -> Path:
    """
    Generate a JSON file ready for reimport into Open WebUI.
    Injects classified tags into meta.tags, adding category and subcategory prefixes.
    Original conversation structure (all branches, history graph) is preserved unchanged.
    """
    class_lookup = {c["id"]: c for c in classified}
    updated = 0

    for chat in original_export:
        chat_id = chat.get("id", "")
        if chat_id not in class_lookup:
            log.debug("Chat id=%s not in classification results, skipping", chat_id[:8])
            continue

        meta = class_lookup[chat_id]
        new_tags = list(meta.get("tags", []))

        macro = meta.get("macro_category")
        sub = meta.get("subcategory")
        if macro:
            new_tags.append(f"cat:{macro}")
        if sub:
            new_tags.append(f"sub:{sub}")

        existing_meta = chat.get("meta", {})
        existing_meta["tags"] = new_tags
        chat["meta"] = existing_meta
        updated += 1

    log.info("Open WebUI output: %d/%d chats updated with tags", updated, len(original_export))

    out_path = Path(OUTPUT_DIR) / "OUTPUT_openwebui_import.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(original_export, f, indent=2, ensure_ascii=False)
    return out_path


def output_obsidian(classified: list, chats_lookup: dict, taxonomy: dict) -> Path:
    """
    Generate an Obsidian vault with one .md file per conversation.
    Files are organized by category/subcategory.
    """
    vault = Path(OUTPUT_DIR) / "OUTPUT_obsidian_vault"
    vault.mkdir(parents=True, exist_ok=True)

    cat_meta = {
        c["id"]: c.get("name", c["id"])
        for c in taxonomy.get("macro_categories", [])
    }

    by_category: dict = defaultdict(list)

    for item in classified:
        if item.get("macro_category", "").startswith("_"):
            log.debug("Skipping error item in Obsidian output: %s", item.get("title"))
            continue

        cat_id = item.get("macro_category", "other")
        sub_id = item.get("subcategory") or "_general"
        cat_name = cat_meta.get(cat_id, cat_id)

        dest_dir = vault / cat_id / sub_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        chat_data = chats_lookup.get(item["id"], {})
        full_text = chat_data.get("full_text", "[text not available]")

        tags_yaml = "\n".join(f"  - {t}" for t in item.get("tags", []))
        if not tags_yaml:
            tags_yaml = "  []"

        date = item.get("date", "unknown")
        title = item.get("title", "No title").replace('"', '\\"')
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

        safe_title = "".join(
            c if c.isalnum() or c in " -_." else "_"
            for c in item.get("title", "untitled")
        )[:70].strip()
        filename = f"{date}_{safe_title}.md"

        (dest_dir / filename).write_text(content, encoding="utf-8")
        by_category[cat_id].append((date, safe_title, sub_id, item.get("tags", [])))

    # Global index
    index_lines = [
        "# Conversation Index",
        "",
        f"*Generated: {datetime.now().strftime('%Y-%m-%d')}*",
        "",
    ]
    for cat_id, items in sorted(by_category.items()):
        cat_name = cat_meta.get(cat_id, cat_id)
        index_lines.append(f"\n## {cat_name} ({len(items)})")
        for date, title, sub, tags in sorted(items):
            tag_str = " ".join(f"`{t}`" for t in tags[:3])
            index_lines.append(
                f"- [[{cat_id}/{sub}/{date}_{title}|{title}]] {tag_str}"
            )

    (vault / "INDEX.md").write_text("\n".join(index_lines), encoding="utf-8")
    log.info("Obsidian vault: %d categories, %d files", len(by_category), sum(len(v) for v in by_category.values()))

    return vault


def output_csv(classified: list) -> Path:
    """Generate a flat CSV catalog of all classifications."""
    out_path = Path(OUTPUT_DIR) / "OUTPUT_catalog.csv"

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "ID", "Title", "Date",
            "Category", "Subcategory",
            "Tags", "Interaction Type",
            "Confidence", "Ambiguity Note",
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

    log.info("CSV catalog: %d rows → %s", len(classified), out_path)
    return out_path


def output_json_catalog(classified: list, chats_lookup: dict) -> Path:
    """Generate a lightweight JSON index (metadata only, no full text)."""
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
    log.info("JSON catalog: %d entries → %s", len(catalog), out_path)
    return out_path


def output_folder_checklist(classified: list, chats_lookup: dict, taxonomy: dict) -> Path:
    """
    Generate a markdown checklist for manually organizing chats into
    Open WebUI folders after import.
    """
    cat_meta = {
        c["id"]: c.get("name", c["id"])
        for c in taxonomy.get("macro_categories", [])
    }
    sub_meta = {}
    for c in taxonomy.get("macro_categories", []):
        for s in c.get("subcategories", []):
            sub_meta[s["id"]] = s.get("name", s["id"])

    by_cat: dict = defaultdict(lambda: defaultdict(list))
    errors: list = []

    for item in classified:
        macro = item.get("macro_category", "")
        if macro.startswith("_"):
            errors.append(item)
            continue
        sub = item.get("subcategory") or "_general"
        chat_data = chats_lookup.get(item["id"], {})
        by_cat[macro][sub].append({
            "title":      item.get("title", "No title"),
            "date":       item.get("date", "?"),
            "confidence": item.get("confidence", "?"),
            "tags":       item.get("tags", []),
            "had_folder": bool(chat_data.get("folder_id")),
            "id":         item.get("id", "")[:8],
        })

    total_ok = sum(len(chats) for subs in by_cat.values() for chats in subs.values())
    total_had_folder = sum(
        1
        for subs in by_cat.values()
        for chats in subs.values()
        for c in chats
        if c["had_folder"]
    )

    lines = [
        "# Open WebUI Folder Checklist",
        "",
        "> **How to use:**",
        "> 1. Import `OUTPUT_openwebui_import.json` into Open WebUI",
        "> 2. Create the folders listed below (one per macro-category)",
        "> 3. For each section, select the chats and move them to the folder",
        "> 4. Check the checkbox once you have moved each chat",
        "> 5. Subcategories: ignore or create sub-folders as you prefer",
        "",
        f"> **Total chats:** {total_ok}  |  "
        f"**Already had a folder (UUID preserved):** {total_had_folder}  |  "
        f"**Classification errors:** {len(errors)}",
        "",
        "---",
        "",
    ]

    for macro_id, subs in sorted(by_cat.items()):
        cat_name = cat_meta.get(macro_id, macro_id)
        total_in_cat = sum(len(v) for v in subs.values())

        lines.append(f"## 📁 {cat_name} ({total_in_cat} chats)")
        lines.append(f"*Create folder: **\"{cat_name}\"***")
        lines.append("")

        for sub_id, chats in sorted(subs.items()):
            sub_label = "General" if sub_id == "_general" else sub_meta.get(sub_id, sub_id)
            lines.append(f"### {sub_label} ({len(chats)})")

            for chat in sorted(chats, key=lambda x: x["date"]):
                conf_icon = {"high": "✅", "medium": "🟡", "low": "🔴",
                             "alta": "✅", "media": "🟡", "bassa": "🔴"}.get(
                    chat["confidence"], "⬜"
                )
                folder_note = " *(had folder)*" if chat["had_folder"] else ""
                tags_str = " ".join(f"`{t}`" for t in chat["tags"][:3])
                lines.append(
                    f"- [ ] **{chat['title']}**{folder_note}  "
                    f"{conf_icon} {chat['date']}  {tags_str}"
                )
            lines.append("")

    if errors:
        lines += [
            "---",
            "",
            f"## ⚠️ Unclassified chats ({len(errors)})",
            "",
            "These chats had errors during classification and must be assigned manually.",
            "",
        ]
        for e in errors:
            lines.append(f"- [ ] **{e.get('title', '?')}** — {e.get('_error', 'unknown error')}")

    lines += [
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Folder | Chats | Subcategories |",
        "|--------|-------|---------------|",
    ]
    for macro_id, subs in sorted(by_cat.items()):
        cat_name = cat_meta.get(macro_id, macro_id)
        total_in_cat = sum(len(v) for v in subs.values())
        n_subs = len([s for s in subs if s != "_general"])
        lines.append(f"| {cat_name} | {total_in_cat} | {n_subs} |")

    out_path = Path(OUTPUT_DIR) / "OUTPUT_folder_checklist.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Folder checklist: %d categories → %s", len(by_cat), out_path)
    return out_path


# ── Entry point ───────────────────────────────────────────────────────────────

def run() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    mode = args[0].lower() if args else "all"

    print_header("PHASE 6 — Final output")
    log.info("Phase 6 started — mode=%s", mode)

    validated = load_json(Path(OUTPUT_DIR) / "phase5_validated.json")
    classified = validated["classified"]

    phase0 = load_json(Path(OUTPUT_DIR) / "phase0_chats.json")
    chats_lookup = {c["id"]: c for c in phase0["chats"]}

    tax_obj = load_json(Path(OUTPUT_DIR) / "phase3_taxonomy.json")
    taxonomy = tax_obj["taxonomy"]

    export_path = Path(EXPORT_FILE)
    if not export_path.exists():
        export_path = Path("..") / EXPORT_FILE

    ok_classified = [
        c for c in classified
        if not c.get("macro_category", "").startswith("_")
    ]
    print(f"Conversations to export: {len(ok_classified)}/{len(classified)}")

    # ── A: Open WebUI ─────────────────────────────────────────────────────────
    if mode in ("all", "openwebui"):
        print("\n[A] Generating Open WebUI import...", end=" ", flush=True)
        if export_path.exists():
            original = load_json(export_path)
            path = output_openwebui(classified, original, taxonomy)
            print(f"✓  {path}")
        else:
            log.error("Original export not found: %s", export_path)
            print(f"✗  Original export not found: {export_path}")

    # ── B: Obsidian ───────────────────────────────────────────────────────────
    if mode in ("all", "obsidian"):
        print("\n[B] Generating Obsidian vault...", end=" ", flush=True)
        path = output_obsidian(ok_classified, chats_lookup, taxonomy)
        n_files = sum(1 for _ in path.rglob("*.md"))
        print(f"✓  {path}  ({n_files} files)")

    # ── C: CSV ────────────────────────────────────────────────────────────────
    if mode in ("all", "csv"):
        print("\n[C] Generating CSV...", end=" ", flush=True)
        path = output_csv(classified)
        print(f"✓  {path}")

    # ── D: JSON catalog ───────────────────────────────────────────────────────
    if mode in ("all", "json"):
        print("\n[D] Generating JSON catalog...", end=" ", flush=True)
        path = output_json_catalog(ok_classified, chats_lookup)
        print(f"✓  {path}")

    # ── E: Folder checklist (always generated) ────────────────────────────────
    print("\n[E] Generating folder checklist...", end=" ", flush=True)
    path = output_folder_checklist(ok_classified, chats_lookup, taxonomy)
    print(f"✓  {path}")

    log.info("Phase 6 complete — mode=%s", mode)
    print(f"\n✓ Phase 6 complete. All files are in {OUTPUT_DIR}/")


if __name__ == "__main__":
    run()
