"""
FASE 5 — Quality Assurance
═══════════════════════════════════════════════════════════════════════════════
Input:  ../output/fase4_classified.json
Output: ../output/fase5_qa_report.md       ← leggibile per l'umano
        ../output/fase5_review_sample.json ← campione da revisionare
        ../output/fase5_validated.json     ← passthrough con flag QA

Cosa fa:
1. Rileva conversazioni con errori o bassa confidenza
2. Rileva anomalie nella distribuzione (categorie sovra/sotto-rappresentate)
3. Campiona N conversazioni per categoria per verifica manuale
4. Genera un report chiaro con i problemi trovati
5. Propone azioni correttive

Dopo questa fase devi:
- Leggere il report
- Compilare il campione (facoltativo ma consigliato)
- Decidere se la qualità è accettabile per procedere con la Fase 6
  oppure se tornare a rifiutare la tassonomia (Fase 3)
═══════════════════════════════════════════════════════════════════════════════
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import random
from datetime import datetime
from collections import Counter
from config import OUTPUT_DIR, QA_SAMPLE_PER_CATEGORY, QA_OVERREPRESENTATION_THRESHOLD
from utils import load_json, save_json, print_header, print_action_required, output_exists, is_force


def run():
    print_header("FASE 5 — Quality Assurance")

    if output_exists("fase5_validated.json", force=is_force()):
        sys.exit(0)

    fase4 = load_json(Path(OUTPUT_DIR) / "fase4_classified.json")
    classified = fase4["classified"]
    total = len(classified)

    print(f"Conversazioni classificate: {total}")

    # ── Check 1: Errori ──────────────────────────────────────────────────────
    errors = [c for c in classified if c.get("_error") or c.get("macro_category") == "_ERRORE"]
    print(f"Errori di classificazione: {len(errors)}")

    # ── Check 2: Bassa confidenza ────────────────────────────────────────────
    low_conf = [c for c in classified if c.get("confidence") == "bassa"]
    print(f"Bassa confidenza: {len(low_conf)}")

    # ── Check 3: Distribuzione categorie ────────────────────────────────────
    cat_counts = Counter(c.get("macro_category", "?") for c in classified)
    anomalies = []

    for cat, count in cat_counts.items():
        pct = count / total
        if pct > QA_OVERREPRESENTATION_THRESHOLD:
            anomalies.append({
                "type": "over",
                "category": cat,
                "count": count,
                "pct": pct,
                "message": f"'{cat}' contiene {count} chat ({pct:.0%}) — potrebbe essere troppo generica",
            })
        if count == 1:
            anomalies.append({
                "type": "singleton",
                "category": cat,
                "count": 1,
                "message": f"'{cat}' contiene solo 1 chat — categoria forse troppo specifica",
            })

    # ── Check 4: Tag vuoti ───────────────────────────────────────────────────
    no_tags = [c for c in classified if not c.get("tags")]
    print(f"Senza tag: {len(no_tags)}")

    # ── Check 5: Distribuzione tag ───────────────────────────────────────────
    all_tags = Counter()
    for c in classified:
        for t in c.get("tags", []):
            all_tags[t] += 1

    # ── Campionamento per verifica manuale ────────────────────────────────────
    sample = []
    for cat in cat_counts:
        cat_items = [c for c in classified if c.get("macro_category") == cat]
        n = min(QA_SAMPLE_PER_CATEGORY, len(cat_items))
        for item in random.sample(cat_items, n):
            sample.append({
                "id":             item["id"],
                "title":          item["title"],
                "date":           item["date"],
                "macro_category": item["macro_category"],
                "subcategory":    item.get("subcategory"),
                "tags":           item.get("tags", []),
                "interaction_type": item.get("interaction_type"),
                "confidence":     item.get("confidence"),
                "ambiguity_note": item.get("ambiguity_note"),
                # Campi da compilare manualmente
                "HUMAN_OK":         None,   # true/false
                "HUMAN_CORRECTION": None,   # correzione se HUMAN_OK è false
            })

    # ── Genera report ─────────────────────────────────────────────────────────
    lines = [
        "# REPORT QA — Fase 5",
        "",
        f"> Generato il {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> Basato su {total} conversazioni classificate",
        "",
        "---",
        "",
        "## 📊 Distribuzione categorie",
        "",
    ]

    for cat, count in cat_counts.most_common():
        pct = count / total
        bar = "█" * int(pct * 50)
        flag = " ⚠️" if pct > QA_OVERREPRESENTATION_THRESHOLD else ""
        lines.append(f"- **{cat}**: {count} ({pct:.0%}){flag}  `{bar}`")

    lines += ["", "---", "", "## 🏷️ Distribuzione tag (top 30)", ""]
    for tag, count in all_tags.most_common(30):
        lines.append(f"- `{tag}`: {count}x")

    if errors:
        lines += ["", "---", "", f"## ❌ Errori di classificazione ({len(errors)})", ""]
        for e in errors[:20]:
            lines.append(f"- **{e.get('title', '?')}** — {e.get('_error', 'errore sconosciuto')}")
        if len(errors) > 20:
            lines.append(f"- ... e altri {len(errors)-20}")

    if low_conf:
        lines += ["", "---", "", f"## ⚠️ Bassa confidenza ({len(low_conf)})", ""]
        for lc in low_conf[:30]:
            note = lc.get("ambiguity_note") or ""
            lines.append(f"- **{lc.get('title', '?')}**")
            lines.append(f"  → `{lc.get('macro_category', '?')}` — {note}")
        if len(low_conf) > 30:
            lines.append(f"- ... e altri {len(low_conf)-30}")

    if anomalies:
        lines += ["", "---", "", "## 🔍 Anomalie nella distribuzione", ""]
        for a in anomalies:
            lines.append(f"- {a['message']}")

    lines += [
        "",
        "---",
        "",
        "## 📋 Prossimi passi",
        "",
        "**Se la qualità è accettabile:**",
        "→ Esegui `python fase6_output.py`",
        "",
        "**Se ci sono troppi errori o anomalie gravi:**",
        "→ Torna alla Fase 3, correggi la tassonomia, ri-approva e ri-esegui la Fase 4",
        "",
        f"**Campione per verifica:** vedi `fase5_review_sample.json` ({len(sample)} chat)",
        "→ Compila `HUMAN_OK` per le chat che hai letto manualmente",
    ]

    report_text = "\n".join(lines)
    report_path = Path(OUTPUT_DIR) / "fase5_qa_report.md"
    report_path.write_text(report_text, encoding="utf-8")

    # Salva campione
    sample_path = Path(OUTPUT_DIR) / "fase5_review_sample.json"
    save_json(sample, sample_path)

    # Passthrough con flag QA
    output = {
        "metadata": {
            "fase": 5,
            "total": total,
            "errors": len(errors),
            "low_confidence": len(low_conf),
            "no_tags": len(no_tags),
            "anomalies": len(anomalies),
            "category_distribution": dict(cat_counts.most_common()),
            "tag_distribution": dict(all_tags.most_common()),
            "sample_size": len(sample),
            "generated_at": datetime.now().isoformat(),
        },
        "classified": classified,   # passthrough dalla fase 4
    }

    out_path = Path(OUTPUT_DIR) / "fase5_validated.json"
    save_json(output, out_path)

    print(f"\n✓ Fase 5 completata")
    print(f"  Errori:          {len(errors)}")
    print(f"  Bassa confidenza:{len(low_conf)}")
    print(f"  Anomalie:        {len(anomalies)}")
    print(f"  Campione QA:     {len(sample)} chat")
    print(f"\n  → Report:   {report_path}")
    print(f"  → Campione: {sample_path}")

    print_action_required([
        "1. Leggi output/fase5_qa_report.md",
        "2. Se ok → python fase6_output.py",
        "3. Se problemi gravi → torna a Fase 3",
    ])


if __name__ == "__main__":
    run()
