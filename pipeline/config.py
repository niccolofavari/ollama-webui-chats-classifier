"""
Centralized pipeline configuration.
Edit this file before running any phase.
"""

# ── Ollama ───────────────────────────────────────────────────────────────────
OLLAMA_URL = "http://localhost:11434/api/generate"

# Default model — can be overridden at runtime with --model <name>
MODEL = "ministral-3:3b"

# Embedding model (optional, for future semantic search phase)
EMBED_MODEL = "nomic-embed-text"

# ── Input file ───────────────────────────────────────────────────────────────
EXPORT_FILE = "chat-export-1773435921370.json"

# ── Directories ──────────────────────────────────────────────────────────────
OUTPUT_DIR     = "output"
CHECKPOINT_DIR = "checkpoints"
PIPELINE_DIR   = "pipeline"

# ── Processing parameters ────────────────────────────────────────────────────
# Maximum characters sent to the LLM per conversation
MAX_CHARS_PER_CHAT = 6000

# Fraction of max_chars taken from the beginning (vs the end) when truncating
TRUNCATE_HEAD_RATIO = 0.45   # 45% head, 55% tail

# LLM retry policy
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds between retries

# Checkpoint interval — save progress every N chats (crash recovery)
CHECKPOINT_EVERY = 20

# ── LLM options per phase ────────────────────────────────────────────────────
LLM_OPTIONS_EXTRACT  = {"temperature": 0.15, "num_predict": 3000}
LLM_OPTIONS_CLUSTER  = {"temperature": 0.10, "num_predict": 4000}
LLM_OPTIONS_TAXONOMY = {"temperature": 0.20, "num_predict": 5000}
LLM_OPTIONS_CLASSIFY = {"temperature": 0.05, "num_predict": 3000}

# ── QA thresholds ────────────────────────────────────────────────────────────
# Number of chats to sample per category during QA
QA_SAMPLE_PER_CATEGORY = 3

# A category containing more than this fraction of all chats is flagged
QA_OVERREPRESENTATION_THRESHOLD = 0.40

# Batch size for topic clustering (phase 2)
CLUSTER_BATCH_SIZE = 120
