from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

JsonDict = Dict[str, Any]

LANG_ALIASES = {
    "jp": "ja",
    "jpn": "ja",
    "japanese": "ja",
    "eng": "en",
    "english": "en",
    "spa": "es",
    "spanish": "es",
}

SUPPORTED_LANGUAGE_CODES = {
    "en", "ja", "es", "fr", "de", "it", "pt", "ko", "zh", "ru"
}

# Script ranges used for lightweight language detection.
RE_HIRAGANA = re.compile(r"[\u3040-\u309f]")
RE_KATAKANA = re.compile(r"[\u30a0-\u30ff]")
RE_CJK = re.compile(r"[\u4e00-\u9fff]")
RE_HANGUL = re.compile(r"[\uac00-\ud7af]")
RE_CYRILLIC = re.compile(r"[\u0400-\u04ff]")
RE_LATIN = re.compile(r"[A-Za-z]")
RE_WORD = re.compile(r"[\w\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af\u0400-\u04ff]+", re.UNICODE)

SPANISH_HINTS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "con",
    "para", "por", "y", "o", "rojo", "azul", "verde", "negro", "blanco",
}
FRENCH_HINTS = {"le", "la", "les", "des", "du", "de", "avec", "pour", "et", "ou"}
GERMAN_HINTS = {"der", "die", "das", "und", "oder", "mit", "für", "von", "ein", "eine"}

TEXT_FIELDS = {"tags", "aliases", "search_tags", "negative", "related", "requires", "excludes"}
META_TEXT_FIELDS = {"title", "notes", "description", "aliases", "search_tags", "related_categories"}

def detect_language_simple(text: str) -> str:
    return detect_language(text)
    
def _unwrap_ui_value(value):
    """
    Gradio/A1111 versions differ in how Dropdown tuple choices are returned.
    Newer builds usually return the choice value, while older builds can return
    the whole (label, value) tuple or even a stringified tuple. Normalize those
    shapes before language routing.
    """
    if isinstance(value, (list, tuple)) and value:
        # Gradio tuple choices are normally (label, value). Prefer value.
        return value[-1]
    if isinstance(value, str):
        text = value.strip()
        # Handle strings like "('Japanese', 'ja')" produced by old Gradio paths.
        if text.startswith("(") and text.endswith(")") and "," in text:
            try:
                import ast
                parsed = ast.literal_eval(text)
                if isinstance(parsed, (list, tuple)) and parsed:
                    return parsed[-1]
            except Exception:
                pass
        return text
    return value


def canonical_lang(code: str | None) -> str:
    code = _unwrap_ui_value(code)
    value = (str(code) if code is not None else "").strip().lower().replace("_", "-")
    value = LANG_ALIASES.get(value, value)
    if "-" in value:
        value = value.split("-", 1)[0]
    return value or "und"


def canonical_mode(mode: str | None) -> str:
    mode = _unwrap_ui_value(mode)
    value = (str(mode) if mode is not None else "").strip().lower()
    aliases = {
        "prompt-safe": "prompt",
        "prompt_safe": "prompt",
        "prompt safe": "prompt",
        "natural language": "natural_language",
        "natural-language": "natural_language",
        "search query": "search",
    }
    return aliases.get(value, value or "prompt")


def normalize_rel_path(path: Path, root: Optional[Path] = None) -> str:
    p = Path(path)
    if root is not None:
        try:
            return p.resolve().relative_to(Path(root).resolve()).as_posix()
        except Exception:
            pass
    return p.as_posix().replace("\\", "/")


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def as_list_str(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(x) for x in value if isinstance(x, (str, int, float)) and str(x).strip()]
    return []


def dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        s = str(item).strip()
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def detect_language(text: str) -> Tuple[str, float, Dict[str, float]]:
    """Small, dependency-free detector. Good enough for routing/search heuristics."""
    text = text or ""
    if not text.strip():
        return "und", 0.0, {}

    total = max(1, len([ch for ch in text if not ch.isspace()]))
    scores: Dict[str, float] = {}

    ja_count = len(RE_HIRAGANA.findall(text)) + len(RE_KATAKANA.findall(text)) + len(RE_CJK.findall(text)) * 0.6
    if ja_count:
        scores["ja"] = min(1.0, ja_count / total * 1.6)

    ko_count = len(RE_HANGUL.findall(text))
    if ko_count:
        scores["ko"] = min(1.0, ko_count / total * 1.6)

    zh_count = len(RE_CJK.findall(text))
    if zh_count and not (RE_HIRAGANA.search(text) or RE_KATAKANA.search(text)):
        scores["zh"] = max(scores.get("zh", 0.0), min(1.0, zh_count / total * 1.4))

    ru_count = len(RE_CYRILLIC.findall(text))
    if ru_count:
        scores["ru"] = min(1.0, ru_count / total * 1.5)

    latin_count = len(RE_LATIN.findall(text))
    if latin_count:
        words = {w.casefold() for w in RE_WORD.findall(text) if RE_LATIN.search(w)}
        # Accent clues can improve Spanish/French routing, but default Latin to English.
        if re.search(r"[áéíóúñü¿¡]", text, re.I) or words & SPANISH_HINTS:
            scores["es"] = max(scores.get("es", 0.0), 0.55)
        if re.search(r"[àâçéèêëîïôûùüÿœ]", text, re.I) or words & FRENCH_HINTS:
            scores["fr"] = max(scores.get("fr", 0.0), 0.52)
        if re.search(r"[äöüß]", text, re.I) or words & GERMAN_HINTS:
            scores["de"] = max(scores.get("de", 0.0), 0.52)
        scores["en"] = max(scores.get("en", 0.0), min(0.80, latin_count / total))

    if not scores:
        return "und", 0.0, {}

    lang, conf = max(scores.items(), key=lambda kv: kv[1])
    return lang, float(round(conf, 4)), {k: float(round(v, 4)) for k, v in sorted(scores.items())}


def detect_language_for_values(values: Sequence[str]) -> Tuple[str, float, Dict[str, float]]:
    text = "\n".join(v for v in values if isinstance(v, str))
    return detect_language(text)


def extract_entry_text_fields(entry: Dict[str, Any]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for field in TEXT_FIELDS:
        values = as_list_str(entry.get(field))
        if values:
            out[field] = dedupe_preserve_order(values)
    return out


def extract_meta_text_fields(meta: Dict[str, Any]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for field in META_TEXT_FIELDS:
        values = as_list_str(meta.get(field))
        if values:
            out[field] = dedupe_preserve_order(values)
    return out


def iter_pack_files(root: Path) -> List[Path]:
    return sorted(p for p in Path(root).rglob("*.json") if p.is_file())


def read_json(path: Path) -> JsonDict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
