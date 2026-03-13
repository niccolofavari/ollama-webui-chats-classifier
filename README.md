# Chat Classifier — Pipeline di catalogazione conversazioni Open WebUI

Pipeline a più fasi per catalogare, taggare e organizzare conversazioni 
esportate da Open WebUI usando un LLM locale (Ollama).

## Filosofia

```
Prima ascolti i dati → poi costruisci la struttura → poi la approvi → poi classifichi
```

Non si assumono categorie a priori. La tassonomia emerge dal corpus.

---

## Struttura

```
.
├── chat-export-*.json          ← il tuo export da Open WebUI
├── pipeline/
│   ├── config.py               ← ⚙️  configura qui modello e parametri
│   ├── utils.py                ← utilità condivise (non eseguire)
│   ├── fase0_split.py          ← split e normalizzazione
│   ├── fase1_extract.py        ← estrazione libera (LLM)
│   ├── fase2_analyze.py        ← analisi corpus e clustering
│   ├── fase3_taxonomy.py       ← proposta tassonomia (LLM)
│   ├── fase4_classify.py       ← classificazione vincolata (LLM)
│   ├── fase5_qa.py             ← quality assurance
│   └── fase6_output.py         ← generazione output finali
├── output/                     ← risultati di ogni fase
├── checkpoints/                ← checkpoint anti-crash (auto)
└── run_pipeline.sh             ← runner interattivo
```

---

## Setup

```bash
# Assicurati di avere Ollama in esecuzione
ollama serve

# Nessuna dipendenza Python esterna richiesta
# (usa solo librerie standard + requests, già disponibile)
pip install requests   # se non già installato
```

---

## Esecuzione

### Modo rapido (runner interattivo)

```bash
cd /Users/nick/Projects/Personal/ollama-webui-chats-classifier
bash run_pipeline.sh
```

### Modo manuale (fase per fase)

```bash
cd pipeline

python fase0_split.py       # ~istantaneo
python fase1_extract.py     # lento — 1 LLM call per chat
python fase2_analyze.py     # medio — clustering e analisi
python fase3_taxonomy.py    # veloce — 1 LLM call
```

> ✋ **STOP** — leggi `output/RIVEDI_TASSONOMIA.md`, modifica  
> `output/fase3_taxonomy.json` se necessario, poi imposta `"approved": true`

```bash
python fase4_classify.py    # lento — 1 LLM call per chat
python fase5_qa.py          # istantaneo
```

> ✋ **STOP** — leggi `output/fase5_qa_report.md`  
> Se la qualità è ok → procedi. Altrimenti torna alla Fase 3.

```bash
# Genera tutti gli output:
python fase6_output.py

# Oppure solo quello che ti serve:
python fase6_output.py openwebui   # reimporta in Open WebUI
python fase6_output.py obsidian    # vault Obsidian
python fase6_output.py csv         # spreadsheet
python fase6_output.py json        # catalogo JSON
```

---

## Fasi — dettaglio

| Fase | Cosa fa | LLM? | Tempo stimato (429 chat) |
|------|---------|------|--------------------------|
| 0 | Split e normalizzazione | No | < 1 min |
| 1 | Estrazione libera degli argomenti | Sì (1x/chat) | ~30-90 min |
| 2 | Clustering e analisi del corpus | Sì (batch) | ~5-15 min |
| 3 | Proposta tassonomia | Sì (1 call) | ~2-5 min |
| — | **REVISIONE UMANA** ✋ | — | quanto ti serve |
| 4 | Classificazione vincolata | Sì (1x/chat) | ~30-90 min |
| 5 | Quality Assurance | No | < 1 min |
| — | **REVISIONE UMANA** ✋ | — | quanto ti serve |
| 6 | Output finale | No | < 1 min |

---

## Output

| File | Descrizione |
|------|-------------|
| `output/OUTPUT_openwebui_import.json` | Reimporta in Open WebUI con tag |
| `output/OUTPUT_obsidian_vault/` | Vault Obsidian con frontmatter YAML |
| `output/OUTPUT_catalog.csv` | Vista tabellare per spreadsheet |
| `output/OUTPUT_catalog.json` | Indice JSON leggero |

---

## Configurazione

Modifica `pipeline/config.py`:

```python
MODEL = "qwen3:32b"         # modello Ollama da usare
MAX_CHARS_PER_CHAT = 6000   # caratteri max per chat (bilanciamento contesto/costo)
CHECKPOINT_EVERY = 20       # salva checkpoint ogni N chat
```

---

## Resume dopo crash

Le fasi 1 e 4 (le più lunghe) salvano un checkpoint ogni `CHECKPOINT_EVERY` chat.
Se il processo si interrompe, riesegui lo stesso script: riprenderà dall'ultima chat processata.

---

## Note sul corpus attuale

- **429 conversazioni** — 2024-11-10 → 2026-03-13
- **411/429** hanno già tag in `meta.tags` (usati come contesto nella Fase 1)
- **Dimensione**: ~102 MB, ~10M caratteri di testo
- **Modelli usati**: principalmente Claude, Gemini, DeepSeek R1
