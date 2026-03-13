#!/usr/bin/env bash
# Runner interattivo della pipeline
# Uso: bash run_pipeline.sh

set -e

PIPELINE_DIR="$(cd "$(dirname "$0")/pipeline" && pwd)"
OUTPUT_DIR="$(cd "$(dirname "$0")" && pwd)/output"

cd "$PIPELINE_DIR"

# Propaga --force e --model a tutte le fasi
FORCE_FLAG=""
MODEL_FLAG=""
args=("$@")
i=0
while [ $i -lt ${#args[@]} ]; do
    arg="${args[$i]}"
    if [ "$arg" = "--force" ]; then
        FORCE_FLAG="--force"
        echo "⚠️  Modalità --force: le fasi già completate verranno rieseguite"
    elif [ "$arg" = "--model" ]; then
        i=$((i+1))
        MODEL_FLAG="--model ${args[$i]}"
        echo "🤖 Modello: ${args[$i]}"
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
    read -r -p "  → Procedere? [y/N] " ans
    case "$ans" in
        [yY]*) return 0 ;;
        *) echo "  Interrotto."; exit 0 ;;
    esac
}

wait_approved() {
    echo ""
    echo "  ┌─────────────────────────────────────────────────┐"
    echo "  │  ✋  AZIONE RICHIESTA                             │"
    echo "  │                                                 │"
    echo "  │  $1"
    echo "  │                                                 │"
    echo "  │  Premi INVIO quando sei pronto...               │"
    echo "  └─────────────────────────────────────────────────┘"
    read -r
}

separator "PIPELINE CLASSIFICAZIONE CONVERSAZIONI"
echo "  Questo script esegue le 6 fasi della pipeline."
echo "  Ti chiederà conferma prima di ogni fase LLM pesante."
echo ""
confirm

# ── Fase 0 ───────────────────────────────────────────────────────────────────
separator "FASE 0 — Split e normalizzazione"
python3 fase0_split.py $FORCE_FLAG

# ── Fase 1 ───────────────────────────────────────────────────────────────────
separator "FASE 1 — Estrazione libera (LLM)"
echo "  Questa fase fa 1 chiamata LLM per ogni conversazione."
echo "  Con 429 chat e qwen3:32b, aspettati 30-90 minuti."
echo "  Il processo riprende automaticamente se interrotto."
echo ""
confirm
python3 fase1_extract.py $FORCE_FLAG $MODEL_FLAG

# ── Fase 2 ───────────────────────────────────────────────────────────────────
separator "FASE 2 — Analisi del corpus"
python3 fase2_analyze.py $FORCE_FLAG $MODEL_FLAG

# ── Fase 3 ───────────────────────────────────────────────────────────────────
separator "FASE 3 — Proposta tassonomia"
python3 fase3_taxonomy.py $FORCE_FLAG $MODEL_FLAG

wait_approved "Leggi output/RIVEDI_TASSONOMIA.md               │
  │  Modifica output/fase3_taxonomy.json              │
  │  Imposta \"approved\": true nel JSON"

# Verifica approvazione
APPROVED=$(python3 -c "
import json
with open('../output/fase3_taxonomy.json') as f:
    d = json.load(f)
print('yes' if d.get('approved') else 'no')
")

if [ "$APPROVED" != "yes" ]; then
    echo ""
    echo "  ❌ La tassonomia non è stata approvata."
    echo "     Imposta \"approved\": true in output/fase3_taxonomy.json"
    exit 1
fi

echo "  ✓ Tassonomia approvata, procedo..."

# ── Fase 4 ───────────────────────────────────────────────────────────────────
separator "FASE 4 — Classificazione vincolata (LLM)"
echo "  Stessa durata della Fase 1 (~30-90 minuti)."
echo ""
confirm
python3 fase4_classify.py $FORCE_FLAG $MODEL_FLAG

# ── Fase 5 ───────────────────────────────────────────────────────────────────
separator "FASE 5 — Quality Assurance"
python3 fase5_qa.py $FORCE_FLAG

wait_approved "Leggi output/fase5_qa_report.md                 │
  │  Controlla il campione in fase5_review_sample.json │
  │  Se ok → procedi. Se no → torna a Fase 3"

# ── Fase 6 ───────────────────────────────────────────────────────────────────
separator "FASE 6 — Output finale"
echo "  Quale output vuoi generare?"
echo "  1) Tutti"
echo "  2) Solo Open WebUI (reimportazione)"
echo "  3) Solo Obsidian vault"
echo "  4) Solo CSV"
echo "  5) Solo catalogo JSON"
echo ""
read -r -p "  Scelta [1]: " choice

case "${choice:-1}" in
    1) python3 fase6_output.py all ;;
    2) python3 fase6_output.py openwebui ;;
    3) python3 fase6_output.py obsidian ;;
    4) python3 fase6_output.py csv ;;
    5) python3 fase6_output.py json ;;
    *) python3 fase6_output.py all ;;
esac

separator "✅ PIPELINE COMPLETATA"
echo "  Risultati in: output/"
echo ""
ls -lh "$OUTPUT_DIR"/OUTPUT_* 2>/dev/null || true
echo ""
