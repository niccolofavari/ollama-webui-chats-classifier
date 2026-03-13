# Open WebUI Chat Classifier

A local-first pipeline to **catalog, tag, and organize** your [Open WebUI](https://github.com/open-webui/open-webui) conversation history using a local LLM via [Ollama](https://ollama.com).

No cloud. No assumptions. The taxonomy emerges from your data.

---

## Philosophy

> First listen to the data → then build the structure → then approve it → then classify.

Most classification tools impose categories upfront. This pipeline does the opposite:

1. Extract topics freely from each conversation (no predefined labels)
2. Cluster and analyze what actually appears in your corpus
3. Propose a taxonomy — **you review and approve it**
4. Only then classify everything using that fixed vocabulary

---

## Features

- **Zero assumptions** — categories emerge from your data, not from a hardcoded list
- **Human in the loop** — two mandatory review checkpoints before irreversible steps
- **Idempotent** — every phase skips if output already exists; use `--force` to rerun
- **Resume on crash** — phases 1 and 4 checkpoint every N chats; restart safely
- **Taxonomy protection** — approved taxonomy cannot be overwritten without `--force`
- **Model agnostic** — any Ollama model, switchable per-run via `--model`
- **Multiple outputs** — reimport into Open WebUI (with tags), Obsidian vault, CSV, JSON

---

## How it works

```
PHASE 0  Export + Split          no LLM  — parse and normalize Open WebUI export
PHASE 1  Free Extraction         LLM     — describe each chat freely, no constraints
PHASE 2  Corpus Analysis         LLM     — cluster synonyms, find natural patterns
PHASE 3  Taxonomy Proposal       LLM     — propose categories from observed patterns
         ✋ HUMAN REVIEW                  — edit and approve before proceeding
PHASE 4  Constrained Classify    LLM     — classify using the approved vocabulary only
PHASE 5  Quality Assurance       no LLM  — anomaly detection, sampling for review
         ✋ HUMAN REVIEW                  — check report before generating output
PHASE 6  Final Output            no LLM  — generate all export formats
```

---

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) running locally
- A model pulled in Ollama (default: `ministral-3:3b`)
- `requests` Python package

```bash
pip install requests
ollama pull ministral-3:3b
```

---

## Setup

```bash
git clone https://github.com/niccolofavari/ollama-webui-chats-classifier
cd ollama-webui-chats-classifier
```

Export your chats from Open WebUI: **Settings → Chats → Export All Chats**

Place the exported JSON in the project root, then edit `pipeline/config.py`:

```python
EXPORT_FILE = "your-export-filename.json"
MODEL       = "ministral-3:3b"   # or any model you have in Ollama
```

---

## Usage

### Interactive runner (recommended)

```bash
bash run_pipeline.sh
```

Walks you through each phase, pauses at human review points, and asks which outputs to generate at the end.

### Manual phase by phase

```bash
cd pipeline

python fase0_split.py       # instant
python fase1_extract.py     # slow — 1 LLM call per chat
python fase2_analyze.py     # medium — batch clustering
python fase3_taxonomy.py    # fast — 1 LLM call
```

> ✋ **STOP** — open `output/RIVEDI_TASSONOMIA.md`, edit `output/fase3_taxonomy.json`
> if needed, then set `"approved": true`

```bash
python fase4_classify.py    # slow — 1 LLM call per chat
python fase5_qa.py          # instant
```

> ✋ **STOP** — read `output/fase5_qa_report.md`. If ok → proceed. If not → back to phase 3.

```bash
python fase6_output.py          # all outputs
python fase6_output.py openwebui  # only Open WebUI reimport
python fase6_output.py obsidian   # only Obsidian vault
python fase6_output.py csv        # only CSV
python fase6_output.py json       # only JSON catalog
```

### CLI options

```bash
# Override model for any phase
python fase1_extract.py --model qwen3:8b

# Force rerun of a completed phase
python fase1_extract.py --force

# Combine
python fase4_classify.py --model qwen3:32b --force

# Pass options to the runner
bash run_pipeline.sh --model qwen3:8b --force
```

---

## Output files

| File | Description |
|------|-------------|
| `output/OUTPUT_openwebui_import.json` | Drop-in replacement for Open WebUI import — original chats with new tags injected into `meta.tags`. All branches and conversation history preserved. |
| `output/OUTPUT_obsidian_vault/` | Obsidian vault — one `.md` per chat, organized by category/subcategory, with YAML frontmatter |
| `output/OUTPUT_catalog.csv` | Spreadsheet-friendly catalog |
| `output/OUTPUT_catalog.json` | Lightweight JSON index (no full text) |
| `output/OUTPUT_folder_checklist.md` | Step-by-step checklist to manually move chats into folders in Open WebUI after import |

---

## Project structure

```
.
├── pipeline/
│   ├── config.py          ← all settings (model, paths, LLM params)
│   ├── utils.py           ← shared utilities (LLM calls, JSON parsing, checkpointing)
│   ├── fase0_split.py     ← parse and normalize export
│   ├── fase1_extract.py   ← free extraction (LLM)
│   ├── fase2_analyze.py   ← corpus analysis and clustering
│   ├── fase3_taxonomy.py  ← taxonomy proposal (LLM)
│   ├── fase4_classify.py  ← constrained classification (LLM)
│   ├── fase5_qa.py        ← quality assurance
│   └── fase6_output.py    ← output generation
├── run_pipeline.sh        ← interactive runner
├── output/                ← generated (gitignored)
├── checkpoints/           ← crash recovery (gitignored)
└── .gitignore
```

---

## Configuration

All settings live in `pipeline/config.py`:

```python
EXPORT_FILE        = "chat-export.json"   # your Open WebUI export
MODEL              = "ministral-3:3b"     # default Ollama model
MAX_CHARS_PER_CHAT = 6000                 # chars sent to LLM per chat (truncated smartly)
CHECKPOINT_EVERY   = 20                   # save checkpoint every N chats
```

LLM parameters per phase:

```python
LLM_OPTIONS_EXTRACT  = {"temperature": 0.15, "num_predict": 2000}
LLM_OPTIONS_CLUSTER  = {"temperature": 0.10, "num_predict": 4000}
LLM_OPTIONS_TAXONOMY = {"temperature": 0.20, "num_predict": 5000}
LLM_OPTIONS_CLASSIFY = {"temperature": 0.05, "num_predict": 2000}
```

---

## Open WebUI export format notes

The export is a JSON array where each chat contains:

- `chat.history.messages` — a **graph** of all messages including regenerated branches
- `chat.messages` — the linear current thread
- `meta.tags` — existing tags (preserved and extended, never overwritten)
- `folder_id` — UUID of the folder the chat belongs to (preserved on reimport to the same instance)

The pipeline linearizes the current thread for LLM processing but passes the **full original structure** through to the output, so no branches or history are lost.

---

## Notes on model choice

Any model available in Ollama works. Larger models produce better taxonomy proposals and more consistent classifications. Smaller models are faster and sufficient for extraction.

Tested with: `ministral-3:3b`, `qwen3.5:9b`, `qwen3:32b`.

For phase 3 (taxonomy proposal) a larger model is recommended if you have one available — you only pay the cost once.

---

## License

MIT
