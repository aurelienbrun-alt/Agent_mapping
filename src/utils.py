from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(value)
    except Exception:
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except Exception:
        return default


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "framework"


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_category(value: Any, *, case_sensitive: bool, trim_spaces: bool) -> str:
    text = "" if value is None else str(value)
    if trim_spaces:
        text = re.sub(r"\s+", " ", text).strip()
    if not case_sensitive:
        text = text.casefold()
    return text


def decode_env_prompt(value: str) -> str:
    return (value or "").replace("\\n", "\n")


def tokenize(text: str) -> list[str]:
    text = normalize_text(text).lower()
    tokens = re.findall(r"[a-zA-Z0-9_\-]{2,}", text)
    stop = {
        "the", "and", "for", "with", "that", "this", "shall", "must", "should", "from", "into",
        "des", "les", "une", "dans", "pour", "avec", "qui", "que", "sur", "aux", "du", "de", "la", "le",
        "et", "ou", "un", "en", "au", "par", "est", "sont", "doit", "doivent"
    }
    return [t for t in tokens if t not in stop]


def stable_hash(obj: Any) -> str:
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


_LANGUAGE_NAMES: dict[str, str] = {
    "fr": "French", "en": "English", "de": "German", "nl": "Dutch",
    "es": "Spanish", "it": "Italian", "pt": "Portuguese", "pl": "Polish",
}


def resolve_language_name(code: str) -> str:
    """Convert a two-letter ISO code to a full English language name.

    The LLM reliably understands "French" or "English" but may inconsistently
    interpret bare codes like "fr" or "en".
    """
    return _LANGUAGE_NAMES.get(str(code).strip().lower(), code)


def render_prompt(template: str, **kwargs: Any) -> str:
    """Render only explicit {placeholder} variables.

    This is safer than str.format for prompts because prompts often contain JSON
    examples with literal braces, such as {text:string}.
    """
    rendered = template or ""
    for key, value in kwargs.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered
