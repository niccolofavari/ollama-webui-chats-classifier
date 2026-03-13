"""
Configurazione centralizzata della pipeline.
Modifica qui prima di eseguire qualsiasi fase.
"""

# ── Ollama ──────────────────────────────────────────────────────────────────
OLLAMA_URL = "http://localhost:11434/api/generate"

# Modello per classificazione/analisi
# Può essere sovrascritto da riga di comando con --model <nome>
MODEL = "ministral-3:3b"

# Modello per embedding (ricerca semantica, fase opzionale)
EMBED_MODEL = "nomic-embed-text"

# ── File di input ────────────────────────────────────────────────────────────
EXPORT_FILE = "chat-export-1773435921370.json"

# ── Directory ────────────────────────────────────────────────────────────────
OUTPUT_DIR      = "output"
CHECKPOINT_DIR  = "checkpoints"
PIPELINE_DIR    = "pipeline"

# ── Parametri di processing ──────────────────────────────────────────────────
# Quanti caratteri max mandare all'LLM per conversazione
MAX_CHARS_PER_CHAT = 6000

# Quanti caratteri tenere dall'inizio (vs dalla fine) in caso di troncamento
TRUNCATE_HEAD_RATIO = 0.45   # 45% inizio, resto dalla fine

# Retry su errori LLM
MAX_RETRIES = 3
RETRY_DELAY = 2  # secondi

# Checkpoint ogni N chat (salvataggio intermedio anti-crash)
CHECKPOINT_EVERY = 20

# ── Parametri LLM ────────────────────────────────────────────────────────────
LLM_OPTIONS_EXTRACT    = {"temperature": 0.15, "num_predict": 2000}
LLM_OPTIONS_CLUSTER    = {"temperature": 0.10, "num_predict": 4000}
LLM_OPTIONS_TAXONOMY   = {"temperature": 0.20, "num_predict": 5000}
LLM_OPTIONS_CLASSIFY   = {"temperature": 0.05, "num_predict": 2000}

# ── Soglie QA ────────────────────────────────────────────────────────────────
# Quante chat campionare per categoria nella fase di QA
QA_SAMPLE_PER_CATEGORY = 3

# Soglia di anomalia: categoria con >X% delle chat è sospetta
QA_OVERREPRESENTATION_THRESHOLD = 0.40

# Batch size per clustering topics (Fase 2)
CLUSTER_BATCH_SIZE = 120
