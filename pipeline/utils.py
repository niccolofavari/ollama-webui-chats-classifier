"""
Shared utilities for all pipeline phases.
"""

import json
import re
import sys
import time
import requests
from datetime import datetime
from pathlib import Path

from config import (
    OLLAMA_URL, MAX_CHARS_PER_CHAT, TRUNCATE_HEAD_RATIO,
    MAX_RETRIES, RETRY_DELAY,
)
from logger import get_logger

log = get_logger("utils")


# ── Text helpers ─────────────────────────────────────────────────────────────

def truncate_smart(text: str, max_chars: int = MAX_CHARS_PER_CHAT) -> str:
    """
    Truncate text preserving both the beginning and the end.
    The beginning provides context; the end often contains the conclusion.
    """
    if len(text) <= max_chars:
        return text

    head = int(max_chars * TRUNCATE_HEAD_RATIO)
    tail = max_chars - head
    omitted = len(text) - head - tail

    log.debug("Truncating text: %d chars → head=%d + tail=%d (omitted %d)", len(text), head, tail, omitted)
    return (
        text[:head]
        + f"\n\n[...{omitted:,} CHARACTERS OMITTED...]\n\n"
        + text[-tail:]
    )


def extract_json(raw: str) -> dict:
    """
    Extract the first valid JSON object from a raw string.

    Handles:
    - Leading/trailing prose around the JSON
    - Markdown code fences (```json ... ```)
    - Multiple JSON objects (returns the first complete one)

    Raises ValueError if no valid JSON object is found.
    """
    # Strip markdown fences
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()

    depth = 0
    start = None
    in_string = False
    escape_next = False

    for i, ch in enumerate(cleaned):
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
            if start is None:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                candidate = cleaned[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError as exc:
                    log.debug("JSON candidate rejected (offset %d): %s", i, exc)
                    start = None  # try next candidate

    raise ValueError(f"No valid JSON found in response:\n{raw[:300]}")


# ── LLM interface ─────────────────────────────────────────────────────────────

def llm_call(
    prompt: str,
    system: str = "",
    model: str = None,
    options: dict = None,
    timeout: int = 180,
) -> str:
    """
    Call Ollama and return the raw response string.
    Retries up to MAX_RETRIES times on network/HTTP errors.
    Raises RuntimeError after all retries are exhausted.
    """
    from config import MODEL as DEFAULT_MODEL

    model = model or DEFAULT_MODEL
    options = options or {}

    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": options,
    }
    if system:
        payload["system"] = system

    log.debug("LLM call → model=%s  prompt_chars=%d", model, len(prompt))

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
            resp.raise_for_status()
            response_text = resp.json().get("response", "")
            log.debug("LLM response ← %d chars (attempt %d)", len(response_text), attempt + 1)
            return response_text
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            log.warning("LLM call timed out (attempt %d/%d, timeout=%ds)", attempt + 1, MAX_RETRIES, timeout)
        except requests.exceptions.HTTPError as exc:
            last_exc = exc
            log.warning("LLM HTTP error (attempt %d/%d): %s", attempt + 1, MAX_RETRIES, exc)
        except Exception as exc:
            last_exc = exc
            log.warning("LLM call error (attempt %d/%d): %s", attempt + 1, MAX_RETRIES, exc)

        if attempt < MAX_RETRIES - 1:
            wait = RETRY_DELAY * (attempt + 1)
            log.debug("Waiting %ds before retry", wait)
            time.sleep(wait)

    raise RuntimeError(f"LLM call failed after {MAX_RETRIES} attempts: {last_exc}")


def _response_is_truncated(raw: str) -> bool:
    """
    Detect whether the response was cut off before the JSON was closed.
    Counts unmatched braces (respecting string literals).
    Returns True if the JSON is not properly terminated.
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
    Call the LLM and parse the response as JSON.

    Retries up to MAX_RETRIES times. On each retry:
    - If the response was truncated (unbalanced braces), doubles num_predict
    - Logs the specific failure reason at WARNING level

    Raises RuntimeError after all retries are exhausted.
    """
    from config import MODEL as DEFAULT_MODEL

    model = model or DEFAULT_MODEL
    required_fields = required_fields or []
    options = dict(options or {})  # copy — we may mutate num_predict

    last_exc: Exception | None = None
    raw: str = ""

    for attempt in range(MAX_RETRIES):
        try:
            raw = llm_call(prompt, system, model, options, timeout)
            parsed = extract_json(raw)

            missing = [f for f in required_fields if f not in parsed]
            if missing:
                raise ValueError(f"Missing required fields in JSON: {missing}")

            return parsed

        except Exception as exc:
            last_exc = exc
            log.warning(
                "llm_call_json attempt %d/%d failed: %s", attempt + 1, MAX_RETRIES, exc
            )
            if attempt < MAX_RETRIES - 1:
                if raw and _response_is_truncated(raw):
                    old_predict = options.get("num_predict", 2000)
                    options["num_predict"] = old_predict * 2
                    log.warning(
                        "Response truncated — doubling num_predict: %d → %d",
                        old_predict, options["num_predict"],
                    )
                    print(
                        f" [retry {attempt+1}: truncated, num_predict → {options['num_predict']}]",
                        end="",
                        flush=True,
                    )
                time.sleep(RETRY_DELAY)

    raise RuntimeError(
        f"llm_call_json failed after {MAX_RETRIES} attempts: {last_exc}"
    )


# ── File I/O ──────────────────────────────────────────────────────────────────

def load_json(path: str | Path) -> any:
    path = Path(path)
    log.debug("Loading JSON: %s", path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: any, path: str | Path, indent: int = 2) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    log.debug("Saving JSON: %s", path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)


def save_checkpoint(data: list, name: str) -> None:
    from config import CHECKPOINT_DIR
    dest = Path(CHECKPOINT_DIR) / f"{name}.json"
    save_json(data, dest)
    log.debug("Checkpoint saved: %s (%d items)", dest, len(data))


def load_checkpoint(name: str) -> list | None:
    from config import CHECKPOINT_DIR
    path = Path(CHECKPOINT_DIR) / f"{name}.json"
    if path.exists():
        data = load_json(path)
        log.info("Checkpoint loaded: %s (%d items)", path, len(data))
        return data
    return None


def clear_checkpoint(name: str) -> None:
    from config import CHECKPOINT_DIR
    path = Path(CHECKPOINT_DIR) / f"{name}.json"
    if path.exists():
        path.unlink()
        log.debug("Checkpoint cleared: %s", path)


# ── Conversation helpers ──────────────────────────────────────────────────────

def linearize_messages(chat_obj: dict) -> list[dict]:
    """
    Open WebUI stores message history as a graph (dict of nodes with
    parentId / childrenIds). This function reconstructs the linear active
    thread by following currentId back to the root.

    Returns an ordered list of messages: [{role, content, timestamp}, ...]
    """
    history = chat_obj.get("chat", {}).get("history", {})
    messages_dict = history.get("messages", {})
    current_id = history.get("currentId")

    if not messages_dict:
        # Fallback: use the flat messages list if available
        direct = chat_obj.get("chat", {}).get("messages", [])
        return [
            {
                "role": m.get("role", ""),
                "content": m.get("content", ""),
                "timestamp": m.get("timestamp", 0),
            }
            for m in direct
        ]

    path: list[dict] = []
    node_id = current_id
    visited: set[str] = set()

    while node_id and node_id not in visited:
        visited.add(node_id)
        node = messages_dict.get(node_id)
        if not node:
            log.debug("Node %r not found in messages dict (broken graph?)", node_id)
            break
        path.append(node)
        node_id = node.get("parentId")

    path.reverse()  # root → current

    return [
        {
            "role": m.get("role", ""),
            "content": m.get("content", ""),
            "timestamp": m.get("timestamp", 0),
        }
        for m in path
    ]


def build_full_text(messages: list[dict]) -> str:
    """Convert a list of messages into a flat text string for the LLM."""
    parts = []
    for m in messages:
        role = m.get("role", "?").upper()
        content = m.get("content", "").strip()
        if content:
            parts.append(f"[{role}]: {content}")
    return "\n\n".join(parts)


# ── CLI helpers ───────────────────────────────────────────────────────────────

def print_header(title: str) -> None:
    width = 60
    print()
    print("─" * width)
    print(f"  {title}")
    print("─" * width)


def output_exists(filename: str, force: bool = False) -> bool:
    """
    Check whether a phase output file already exists.

    Returns True (and prints a message) if the file exists and force=False.
    The caller should do sys.exit(0) when this returns True.
    """
    from config import OUTPUT_DIR

    path = Path(OUTPUT_DIR) / filename
    if path.exists() and not force:
        print(f"\n⚠️  Output already exists: {path}")
        print(f"   This phase has already been completed.")
        print(f"   To rerun from scratch: python <phase>.py --force")
        print(f"   To use the existing output: proceed to the next phase.")
        return True
    return False


def is_force() -> bool:
    """Return True if --force was passed on the command line."""
    return "--force" in sys.argv


def resolve_model() -> str:
    """
    Determine the model to use, in priority order:
      1. --model <name> on the command line
      2. MODEL in config.py

    Call once at the start of each phase and use the returned value.
    Also updates config.MODEL in-process so llm_call() sees it as default.
    """
    import config

    args = sys.argv[1:]
    if "--model" in args:
        idx = args.index("--model")
        if idx + 1 < len(args):
            model = args[idx + 1]
            config.MODEL = model  # propagate to module-level default
            log.info("Model overridden via --model: %s", model)
            return model

    return config.MODEL


def print_action_required(steps: list[str]) -> None:
    """Print a prominent 'human action required' box to stdout."""
    width = 54
    border = "─" * width
    print()
    print(f"┌{border}┐")
    print(f"│  ✋  ACTION REQUIRED BEFORE PROCEEDING{' ' * 16}│")
    print(f"├{border}┤")
    for step in steps:
        # Wrap long lines
        while len(step) > width - 2:
            print(f"│  {step[:width-2]}│")
            step = "   " + step[width - 2:]
        print(f"│  {step:<{width-2}}│")
    print(f"└{border}┘")
    print()
