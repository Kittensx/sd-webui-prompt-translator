from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Set

DEFAULT_EXACT_TOKENS = {
    "1girl",
    "1boy",
    "2girls",
    "2boys",
    "solo",
    "masterpiece",
    "best quality",
    "highres",
    "absurdres",
    "ultra detailed",
    "official art",
    "safe",
    "sensitive",
    "questionable",
    "explicit",
}

DEFAULT_PREFIX_TOKENS = {
    "<lora:",
    "<lyco:",
    "<hypernet:",
    "<embedding:",
    "embedding:",
}

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
USER_DIR = ROOT / "user"
DEFAULT_PATH = DATA_DIR / "default_protected_prompt_tokens.json"
USER_PATH = USER_DIR / "protected_prompt_tokens.json"


def _empty_payload() -> Dict[str, object]:
    return {
        "version": 2,
        "exact": [],
        "prefix": [],
        "notes": "User-managed protected prompt tokens. Exact tokens match full spans; prefix tokens match span starts.",
    }


def _default_payload() -> Dict[str, object]:
    return {
        "version": 2,
        "exact": sorted(DEFAULT_EXACT_TOKENS),
        "prefix": sorted(DEFAULT_PREFIX_TOKENS),
    }


def _ensure_defaults() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    USER_DIR.mkdir(parents=True, exist_ok=True)

    if not DEFAULT_PATH.exists():
        DEFAULT_PATH.write_text(json.dumps(_default_payload(), indent=2, ensure_ascii=False), encoding="utf8")

    if not USER_PATH.exists():
        USER_PATH.write_text(json.dumps(_empty_payload(), indent=2, ensure_ascii=False), encoding="utf8")


def _coerce_payload(data: object) -> Dict[str, List[str]]:
    if not isinstance(data, dict):
        return {"exact": [], "prefix": []}

    exact = data.get("exact", [])
    prefix = data.get("prefix", [])

    # Backwards compatibility for the v1 shape: {"tokens": [...]}.
    if not exact and not prefix and isinstance(data.get("tokens"), list):
        legacy = [str(x).strip() for x in data.get("tokens", []) if str(x).strip()]
        exact = [x for x in legacy if not x.endswith(":") and not x.startswith("<")]
        prefix = [x for x in legacy if x.endswith(":") or x.startswith("<")]

    return {
        "exact": [str(x).strip() for x in exact if str(x).strip()] if isinstance(exact, list) else [],
        "prefix": [str(x).strip() for x in prefix if str(x).strip()] if isinstance(prefix, list) else [],
    }


def _load(path: Path) -> Dict[str, Set[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf8"))
    except Exception:
        return {"exact": set(), "prefix": set()}

    payload = _coerce_payload(data)
    return {
        "exact": {x for x in payload["exact"] if x},
        "prefix": {x for x in payload["prefix"] if x},
    }


def get_protected_token_sets() -> Dict[str, Set[str]]:
    _ensure_defaults()
    default_tokens = _load(DEFAULT_PATH)
    user_tokens = _load(USER_PATH)
    return {
        "exact": default_tokens["exact"] | user_tokens["exact"],
        "prefix": default_tokens["prefix"] | user_tokens["prefix"],
    }


def get_protected_tokens() -> Set[str]:
    tokens = get_protected_token_sets()
    return tokens["exact"] | tokens["prefix"]


def save_user_tokens(tokens: Iterable[str]) -> None:
    exact: Set[str] = set()
    prefix: Set[str] = set()
    for token in tokens:
        value = str(token).strip()
        if not value:
            continue
        if value.endswith(":") or value.startswith("<"):
            prefix.add(value)
        else:
            exact.add(value)
    save_user_token_sets(exact=exact, prefix=prefix)


def save_user_token_sets(*, exact: Iterable[str] = (), prefix: Iterable[str] = ()) -> None:
    _ensure_defaults()
    payload = _empty_payload()
    payload["exact"] = sorted({str(x).strip() for x in exact if str(x).strip()})
    payload["prefix"] = sorted({str(x).strip() for x in prefix if str(x).strip()})
    USER_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf8")


def is_protected_token(text: str) -> bool:
    candidate = (text or "").strip().lower()
    if not candidate:
        return False

    token_sets = get_protected_token_sets()
    exact = {x.lower() for x in token_sets["exact"]}
    prefix = {x.lower() for x in token_sets["prefix"]}

    if candidate in exact:
        return True

    return any(candidate.startswith(token) for token in prefix)
