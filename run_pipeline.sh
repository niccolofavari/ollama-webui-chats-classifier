#!/usr/bin/env bash
# Interactive pipeline runner
# Usage: bash run_pipeline.sh [--model <name>] [--force]

set -e

PIPELINE_DIR="$(cd "$(dirname "$0")/pipeline" && pwd)"
OUTPUT_DIR="$(cd "$(dirname "$0")" && pwd)/output"

cd "$PIPELINE_DIR"

# Parse --force and --model flags, propagate to all LLM phases
FORCE_FLAG=""
MODEL_FLAG=""
args=("$@")
i=0
while [ $i -lt ${#args[@]} ]; do
    arg="${args[$i]}"
    if [ "$arg" = "--force" ]; then
        FORCE_FLAG="--force"
        echo "⚠️  --force mode: completed phases will be rerun"
    elif [ "$arg" = "--model" ]; then
        i=$((i+1))
        MODEL_FLAG="--model ${args[$i]}"
        echo "🤖 Model: ${args[$i]}"
    fi
    i=$((i+1))
done

separator() {
    echo ""
    echo "══════════════════════════════════════════════════════"
    echo "  $1"
    echo "══════════════════════════════════════════════════════"
    echo ""
}

confirm() {
    read -r -p "  → Proceed? [y/N] " ans
    case "$ans" in
        [yY]*) return 0 ;;
        *) echo "  Aborted."; exit 0 ;;
    esac
}

wait_for_human() {
    echo ""
    echo "  ┌─────────────────────────────────────────────────┐"
    echo "  │  ✋  ACTION REQUIRED                              │"
    echo "  │                                                 │"
    echo "  │  $1"
    echo "  │                                                 │"
    echo "  │  Press ENTER when ready...                      │"
    echo "  └─────────────────────────────────────────────────┘"
    read -r
}

separator "CONVERSATION CLASSIFICATION PIPELINE"
echo "  This script runs all 6 phases of the pipeline."
echo "  It will ask for confirmation before each heavy LLM phase."
echo ""
confirm

# ── Phase 0 ──────────────────────────────────────────────────────────────────
separator "PHASE 0 — Split and normalize"
python3 phase0_split.py $FORCE_FLAG

# ── Phase 1 ──────────────────────────────────────────────────────────────────
separator "PHASE 1 — Free extraction (LLM)"
echo "  This phase makes 1 LLM call per conversation."
echo "  Expect 30–90 minutes depending on model and corpus size."
echo "  The process resumes automatically if interrupted."
echo ""
confirm
python3 phase1_extract.py $FORCE_FLAG $MODEL_FLAG

# ── Phase 2 ──────────────────────────────────────────────────────────────────
separator "PHASE 2 — Corpus analysis"
python3 phase2_analyze.py $FORCE_FLAG $MODEL_FLAG

# ── Phase 3 ──────────────────────────────────────────────────────────────────
separator "PHASE 3 — Taxonomy proposal"
python3 phase3_taxonomy.py $FORCE_FLAG $MODEL_FLAG

wait_for_human "Read output/REVIEW_TAXONOMY.md                  │
  │  Edit output/phase3_taxonomy.json if needed       │
  │  Set \"approved\": true in the JSON"

# Verify approval
APPROVED=$(python3 -c "
import json
with open('../output/phase3_taxonomy.json') as f:
    d = json.load(f)
print('yes' if d.get('approved') else 'no')
")

if [ "$APPROVED" != "yes" ]; then
    echo ""
    echo "  ❌ Taxonomy not approved."
    echo "     Set \"approved\": true in output/phase3_taxonomy.json"
    exit 1
fi

echo "  ✓ Taxonomy approved, continuing..."

# ── Phase 4 ──────────────────────────────────────────────────────────────────
separator "PHASE 4 — Constrained classification (LLM)"
echo "  Similar duration to Phase 1 (~30–90 minutes)."
echo ""
confirm
python3 phase4_classify.py $FORCE_FLAG $MODEL_FLAG

# ── Phase 5 ──────────────────────────────────────────────────────────────────
separator "PHASE 5 — Quality Assurance"
python3 phase5_qa.py $FORCE_FLAG

wait_for_human "Read output/phase5_qa_report.md                 │
  │  Review sample: phase5_review_sample.json          │
  │  If ok → proceed. If not → go back to Phase 3"

# ── Phase 6 ──────────────────────────────────────────────────────────────────
separator "PHASE 6 — Final output"
echo "  Which outputs do you want to generate?"
echo "  1) All"
echo "  2) Open WebUI import only"
echo "  3) Obsidian vault only"
echo "  4) CSV only"
echo "  5) JSON catalog only"
echo ""
read -r -p "  Choice [1]: " choice

case "${choice:-1}" in
    1) python3 phase6_output.py all ;;
    2) python3 phase6_output.py openwebui ;;
    3) python3 phase6_output.py obsidian ;;
    4) python3 phase6_output.py csv ;;
    5) python3 phase6_output.py json ;;
    *) python3 phase6_output.py all ;;
esac

separator "✅ PIPELINE COMPLETE"
echo "  Results are in: output/"
echo ""
ls -lh "$OUTPUT_DIR"/OUTPUT_* 2>/dev/null || true
echo ""
