"""
Phase 5 — Quality Assurance
===============================================================================
Input:  output/phase4_classified.json
Output: output/phase5_qa_report.md       ← human-readable report
        output/phase5_review_sample.json ← sample for manual review
        output/phase5_validated.json     ← passthrough with QA flags

What it does:
1. Detects classification errors and low-confidence items
2. Detects distribution anomalies (over/under-represented categories)
3. Samples N conversations per category for manual verification
4. Generates a clear report with all issues found
5. Suggests corrective actions

After this phase you should:
- Read the report
- Review the sample (recommended)
- Decide if quality is acceptable to proceed to Phase 6,
  or go back and revise the taxonomy (Phase 3)
===============================================================================
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import random
from datetime import datetime
from collections import Counter

from config import OUTPUT_DIR, QA_SAMPLE_PER_CATEGORY, QA_OVERREPRESENTATION_THRESHOLD
from logger import get_logger
from utils import load_json, save_json, print_header, print_action_required, output_exists, is_force

log = get_logger("phase5")

# Confidence values considered "low" regardless of language
LOW_CONFIDENCE_VALUES = {"low", "bassa"}


def run() -> None:
    print_header("PHASE 5 — Quality Assurance")

    if output_exists("phase5_validated.json", force=is_force()):
        sys.exit(0)

    phase4 = load_json(Path(OUTPUT_DIR) / "phase4_classified.json")
    classified = phase4["classified"]
    total = len(classified)

    log.info("Phase 5 started — total=%d", total)
    print(f"Classified conversations: {total}")

    # ── Check 1: Classification errors ───────────────────────────────────────
    errors = [c for c in classified if c.get("_error") or c.get("macro_category") == "_ERROR"]
    log.info("Classification errors: %d", len(errors))
    print(f"Classification errors:  {len(errors)}")

    # ── Check 2: Low confidence ───────────────────────────────────────────────
    low_conf = [c for c in classified if c.get("confidence", "").lower() in LOW_CONFIDENCE_VALUES]
    log.info("Low confidence items: %d", len(low_conf))
    print(f"Low confidence:        {len(low_conf)}")

    # ── Check 3: Category distribution anomalies ──────────────────────────────
    cat_counts = Counter(c.get("macro_category", "?") for c in classified)
    anomalies: list[dict] = []

    for cat, count in cat_counts.items():
        pct = count / total
        if pct > QA_OVERREPRESENTATION_THRESHOLD:
            msg = f"'{cat}' contains {count} chats ({pct:.0%}) — may be too generic"
            anomalies.append({"type": "over", "category": cat, "count": count, "pct": pct, "message": msg})
            log.warning("Distribution anomaly (over): %s", msg)
        if count == 1:
            msg = f"'{cat}' contains only 1 chat — category may be too specific"
            anomalies.append({"type": "singleton", "category": cat, "count": 1, "message": msg})
            log.info("Distribution anomaly (singleton): %s", msg)

    # ── Check 4: Missing tags ─────────────────────────────────────────────────
    no_tags = [c for c in classified if not c.get("tags")]
    log.info("Without tags: %d", len(no_tags))
    print(f"Without tags:          {len(no_tags)}")

    # ── Check 5: Tag distribution ─────────────────────────────────────────────
    all_tags: Counter = Counter()
    for c in classified:
        for t in c.get("tags", []):
            all_tags[t] += 1

    # ── Sampling for manual review ────────────────────────────────────────────
    sample: list[dict] = []
    for cat in cat_counts:
        cat_items = [c for c in classified if c.get("macro_category") == cat]
        n = min(QA_SAMPLE_PER_CATEGORY, len(cat_items))
        for item in random.sample(cat_items, n):
            sample.append({
                "id":               item["id"],
                "title":            item["title"],
                "date":             item["date"],
                "macro_category":   item["macro_category"],
                "subcategory":      item.get("subcategory"),
                "tags":             item.get("tags", []),
                "interaction_type": item.get("interaction_type"),
                "confidence":       item.get("confidence"),
                "ambiguity_note":   item.get("ambiguity_note"),
                # Fields to fill in manually
                "HUMAN_OK":         None,    # true / false
                "HUMAN_CORRECTION": None,    # correction if HUMAN_OK is false
            })

    log.info("Sample generated: %d conversations", len(sample))

    # ── Generate report ───────────────────────────────────────────────────────
    lines = [
        "# QA REPORT — Phase 5",
        "",
        f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> Based on {total} classified conversations",
        "",
        "---",
        "",
        "## Category distribution",
        "",
    ]

    for cat, count in cat_counts.most_common():
        pct = count / total
        bar = "█" * int(pct * 50)
        flag = " ⚠️" if pct > QA_OVERREPRESENTATION_THRESHOLD else ""
        lines.append(f"- **{cat}**: {count} ({pct:.0%}){flag}  `{bar}`")

    lines += ["", "---", "", "## Tag distribution (top 30)", ""]
    for tag, count in all_tags.most_common(30):
        lines.append(f"- `{tag}`: {count}x")

    if errors:
        lines += ["", "---", "", f"## Classification errors ({len(errors)})", ""]
        for e in errors[:20]:
            lines.append(f"- **{e.get('title', '?')}** — {e.get('_error', 'unknown error')}")
        if len(errors) > 20:
            lines.append(f"- ... and {len(errors)-20} more")

    if low_conf:
        lines += ["", "---", "", f"## Low confidence ({len(low_conf)})", ""]
        for lc in low_conf[:30]:
            note = lc.get("ambiguity_note") or ""
            lines.append(f"- **{lc.get('title', '?')}**")
            lines.append(f"  → `{lc.get('macro_category', '?')}` — {note}")
        if len(low_conf) > 30:
            lines.append(f"- ... and {len(low_conf)-30} more")

    if anomalies:
        lines += ["", "---", "", "## Distribution anomalies", ""]
        for a in anomalies:
            lines.append(f"- {a['message']}")

    lines += [
        "",
        "---",
        "",
        "## Next steps",
        "",
        "**If quality is acceptable:**",
        "→ Run `python phase6_output.py`",
        "",
        "**If there are too many errors or serious anomalies:**",
        "→ Go back to Phase 3, revise the taxonomy, re-approve, and rerun Phase 4",
        "",
        f"**Manual review sample:** see `phase5_review_sample.json` ({len(sample)} chats)",
        "→ Fill in `HUMAN_OK` for any chats you review manually",
    ]

    report_text = "\n".join(lines)
    report_path = Path(OUTPUT_DIR) / "phase5_qa_report.md"
    report_path.write_text(report_text, encoding="utf-8")

    sample_path = Path(OUTPUT_DIR) / "phase5_review_sample.json"
    save_json(sample, sample_path)

    output = {
        "metadata": {
            "phase": 5,
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
        "classified": classified,  # passthrough from phase 4
    }

    out_path = Path(OUTPUT_DIR) / "phase5_validated.json"
    save_json(output, out_path)

    log.info(
        "Phase 5 complete — errors=%d  low_confidence=%d  anomalies=%d  sample=%d",
        len(errors), len(low_conf), len(anomalies), len(sample),
    )
    print(f"\n✓ Phase 5 complete")
    print(f"  Errors:         {len(errors)}")
    print(f"  Low confidence: {len(low_conf)}")
    print(f"  Anomalies:      {len(anomalies)}")
    print(f"  QA sample:      {len(sample)} chats")
    print(f"\n  → Report:  {report_path}")
    print(f"  → Sample:  {sample_path}")

    print_action_required([
        "1. Read output/phase5_qa_report.md",
        "2. If ok → python phase6_output.py",
        "3. If issues → go back to Phase 3",
    ])


if __name__ == "__main__":
    run()
