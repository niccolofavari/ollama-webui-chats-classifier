"""
Centralized logging for the pipeline.

Usage in any phase:
    from logger import get_logger
    log = get_logger("phase1")
    log.info("Processing %d chats", total)
    log.warning("Truncation detected, retrying with num_predict=%d", n)
    log.error("LLM call failed: %s", exc)

Log files are written to output/logs/<phase>.log alongside the JSON outputs.
The console shows WARNING+ by default; the file captures everything (DEBUG+).
"""

import logging
import sys
from pathlib import Path


_loggers: dict[str, logging.Logger] = {}

LOG_DIR = Path(__file__).parent / "output" / "logs"

# Console format: concise
_CONSOLE_FORMAT = "%(levelname)s  %(message)s"

# File format: full detail for debugging
_FILE_FORMAT = "%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str, level: int = logging.DEBUG) -> logging.Logger:
    """
    Return (or create) a named logger.

    Args:
        name:  Short name, e.g. "phase1", "utils", "phase4".
               Used as the log file name: output/logs/<name>.log
        level: Root capture level (default DEBUG — the file sees everything).
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False  # don't bubble up to root logger

    # ── Console handler (WARNING and above) ──────────────────────────────────
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    logger.addHandler(ch)

    # ── File handler (DEBUG and above) ───────────────────────────────────────
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"{name}.log"
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt=_DATE_FORMAT))
        logger.addHandler(fh)
    except OSError as e:
        # If the log directory cannot be created, continue with console only
        logger.warning("Cannot open log file for '%s': %s", name, e)

    _loggers[name] = logger
    return logger


def set_console_level(level: int) -> None:
    """
    Adjust the console verbosity for all existing loggers.
    Call with logging.DEBUG to see everything during development.
    """
    for logger in _loggers.values():
        for handler in logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.FileHandler
            ):
                handler.setLevel(level)
