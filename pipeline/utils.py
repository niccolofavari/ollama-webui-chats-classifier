"""
Utilità condivise tra tutte le fasi della pipeline.
"""

import json
import re
import time
import requests
from datetime import datetime
from pathlib import Path

from config import (
    OLLAMA_URL, MAX_CHARS_PER_CHAT, TRUNCATE_HEAD_RATIO,
    MAX_RETRIES, RETRY_DELAY
)


# ── Testo ────────────────────────────────────────────────────────────────────

def truncate_smart(text: str, max_chars: int = MAX_CHARS_PER_CHAT) -> str:
    """
    Tronca il testo preservando inizio e fine.
    L'inizio dà il contesto, la fine spesso contiene la conclusione.
    """
    if len(text) <= max_chars:
        return text

    head = int(max_chars * TRUNCATE_HEAD_RATIO)
    tail = max_chars - head
    omitted = len(text) - head - tail

    return (
        text[:head]
        + f"\n\n[...{omitted:,} CARATTERI OMESSI...]\n\n"
        + text[-tail:]
    )


def extract_json(raw: str) -> dict:
    """
    Estrae il primo oggetto JSON valido da una stringa di testo.
    Gestisce il caso in cui l'LLM aggiunge testo prima/dopo il JSON,
    e il caso di blocchi ```json ... ```.
    """
    # Prova prima a rimuovere eventuali blocchi markdown
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()

    # Cerca il primo { ... } bilanciato
    depth = 0
    start = None
    for i, ch in enumerate(cleaned):
        if ch == "{":
            if start is None:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                candidate = cleaned[start:i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    # Potrebbe esserci un secondo JSON più avanti
                    start = None

    raise ValueError(f"Nessun JSON valido trovato nella risposta:\n{raw[:300]}")


# ── LLM ─────────────────────────────────────────────────────────────────────

def llm_call(
    prompt: str,
    system: str = "",
    model: str = None,
    options: dict = None,
    timeout: int = 180,
) -> str:
    """
    Chiama Ollama e restituisce la stringa di risposta.
    Rilancia eccezione solo dopo MAX_RETRIES tentativi falliti.
    """
    from config import MODEL as DEFAULT_MODEL
    model = model or DEFAULT_MODEL
    options = options or {}

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": options,
    }
    if system:
        payload["system"] = system

    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json().get("response", "")
        except Exception as e:
            last_exc = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))

    raise RuntimeError(f"LLM call fallita dopo {MAX_RETRIES} tentativi: {last_exc}")


def _is_truncated(raw: str) -> bool:
    """
    Rileva se la risposta è stata troncata prima della chiusura del JSON.
    Conta le graffe aperte e chiuse: se non si bilanciano, è troncato.
    """
    depth = 0
    in_string = False
    escape_next = False
    for ch in raw:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    return depth != 0


def llm_call_json(
    prompt: str,
    system: str = "",
    model: str = None,
    options: dict = None,
    required_fields: list = None,
    timeout: int = 180,
) -> dict:
    """
    Come llm_call ma fa il parsing JSON e valida i campi richiesti.
    Ritenta se il JSON non è valido o mancano campi obbligatori.
    Se rileva un troncamento (JSON non chiuso), raddoppia num_predict al retry.
    """
    from config import MODEL as DEFAULT_MODEL
    model = model or DEFAULT_MODEL
    required_fields = required_fields or []
    options = dict(options or {})  # copia per non modificare l'originale

    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            raw = llm_call(prompt, system, model, options, timeout)
            parsed = extract_json(raw)
            for field in required_fields:
                if field not in parsed:
                    raise ValueError(f"Campo mancante nel JSON: '{field}'")
            return parsed
        except Exception as e:
            last_exc = e
            if attempt < MAX_RETRIES - 1:
                # Se il JSON era troncato, raddoppia num_predict per il retry
                if _is_truncated(raw if "raw" in dir() else ""):
                    old = options.get("num_predict", 2000)
                    options["num_predict"] = old * 2
                    print(f" [retry {attempt+1}: troncato, aumento num_predict a {options['num_predict']}]", end="", flush=True)
                time.sleep(RETRY_DELAY)

    raise RuntimeError(
        f"llm_call_json fallita dopo {MAX_RETRIES} tentativi: {last_exc}"
    )


# ── I/O ──────────────────────────────────────────────────────────────────────

def load_json(path: str | Path) -> any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: any, path: str | Path, indent: int = 2) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)


def save_checkpoint(data: list, name: str) -> None:
    from config import CHECKPOINT_DIR
    save_json(data, Path(CHECKPOINT_DIR) / f"{name}.json")


def load_checkpoint(name: str) -> list | None:
    from config import CHECKPOINT_DIR
    p = Path(CHECKPOINT_DIR) / f"{name}.json"
    if p.exists():
        return load_json(p)
    return None


def clear_checkpoint(name: str) -> None:
    from config import CHECKPOINT_DIR
    p = Path(CHECKPOINT_DIR) / f"{name}.json"
    if p.exists():
        p.unlink()


# ── Conversazioni ─────────────────────────────────────────────────────────────

def linearize_messages(chat_obj: dict) -> list[dict]:
    """
    Open WebUI salva la history come un grafo (dict di nodi con parentId/childrenIds).
    Questa funzione ricostruisce il thread lineare seguendo currentId a ritroso.
    Restituisce la lista ordinata di messaggi {role, content, timestamp}.
    """
    history = chat_obj.get("chat", {}).get("history", {})
    messages_dict = history.get("messages", {})
    current_id = history.get("currentId")

    if not messages_dict:
        # Fallback: prova il campo messages diretto
        direct = chat_obj.get("chat", {}).get("messages", [])
        return [
            {"role": m.get("role", ""), "content": m.get("content", ""), "timestamp": m.get("timestamp", 0)}
            for m in direct
        ]

    # Ricostruisci il path da root a currentId
    # Costruiamo un lookup inverso: id → nodo
    # Poi risaliamo da currentId fino a root (parentId == None)
    path = []
    node_id = current_id
    visited = set()

    while node_id and node_id not in visited:
        visited.add(node_id)
        node = messages_dict.get(node_id)
        if not node:
            break
        path.append(node)
        node_id = node.get("parentId")

    path.reverse()  # ora è root → current

    return [
        {
            "role": m.get("role", ""),
            "content": m.get("content", ""),
            "timestamp": m.get("timestamp", 0),
        }
        for m in path
    ]


def build_full_text(messages: list[dict]) -> str:
    """Converte la lista di messaggi in testo lineare per l'LLM."""
    parts = []
    for m in messages:
        role = m.get("role", "?").upper()
        content = m.get("content", "").strip()
        if content:
            parts.append(f"[{role}]: {content}")
    return "\n\n".join(parts)


# ── Stampa ───────────────────────────────────────────────────────────────────

def print_header(title: str) -> None:
    width = 60
    print()
    print("─" * width)
    print(f"  {title}")
    print("─" * width)


def output_exists(filename: str, force: bool = False) -> bool:
    """
    Controlla se un file di output esiste già.
    Se esiste e --force non è passato, stampa un avviso e restituisce True
    (il chiamante dovrebbe fare sys.exit(0)).
    Se force=True, sovrascrive senza chiedere.
    """
    from config import OUTPUT_DIR
    path = Path(OUTPUT_DIR) / filename
    if path.exists() and not force:
        print(f"\n⚠️  Output già esistente: {path}")
        print(f"   La fase è già stata completata.")
        print(f"   Per rieseguirla da zero: python <fase>.py --force")
        print(f"   Per usare l'output esistente: vai alla fase successiva.")
        return True
    return False


def is_force() -> bool:
    """Controlla se --force è passato come argomento."""
    import sys
    return "--force" in sys.argv


def resolve_model() -> str:
    """
    Restituisce il modello da usare, con questa precedenza:
      1. --model <nome>  passato da riga di comando
      2. MODEL in config.py (default)

    Chiama questa funzione UNA VOLTA all'inizio di ogni fase
    e usa il valore restituito — non importare MODEL direttamente.

    Esempio:
        model = resolve_model()
        result = llm_call(prompt, model=model)
    """
    import sys
    import config

    args = sys.argv[1:]
    if "--model" in args:
        idx = args.index("--model")
        if idx + 1 < len(args):
            model = args[idx + 1]
            # Sovrascrive anche config.MODEL in memoria
            # così llm_call() lo vede come default
            config.MODEL = model
            return model

    return config.MODEL


def print_action_required(steps: list[str]) -> None:
    print()
    print("┌" + "─" * 52 + "┐")
    print("│  ✋  AZIONE RICHIESTA PRIMA DI PROCEDERE          │")
    print("├" + "─" * 52 + "┤")
    for step in steps:
        # Pad to 50 chars
        line = f"  {step}"
        print(f"│{line:<52}│")
    print("└" + "─" * 52 + "┘")
    print()
