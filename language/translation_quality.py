from __future__ import annotations

"""
Prompt-aware translation quality scoring.

This does not prove correctness. It catches common bad MT behavior for Stable
Diffusion prompt fragments: hallucinated named places, prose expansion,
unexpected verbs/actions, wrong script, and sentence-like punctuation.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional

try:
    from language_utils import canonical_lang
except Exception:
    from .language_utils import canonical_lang

TARGET_SCRIPT_HINTS = {
    "ja": re.compile(r"[\u3040-\u30ff\u3400-\u9fff]"),
    "zh": re.compile(r"[\u3400-\u9fff]"),
    "ko": re.compile(r"[\uac00-\ud7af]"),
    "ru": re.compile(r"[\u0400-\u04ff]"),
    "ar": re.compile(r"[\u0600-\u06ff]"),
    "hi": re.compile(r"[\u0900-\u097f]"),
    "th": re.compile(r"[\u0e00-\u0e7f]"),
}

# Common proper nouns that indicate hallucination for short prompt fragments.
# This is intentionally small and tuneable.
HALLUCINATION_TERMS = {
    "nile", "ナイル", "egypt", "エジプト", "america", "アメリカ", "tokyo", "東京",
    "paris", "パリ", "china", "中国", "japan", "日本", "india", "インド",
}

BAD_PROMPT_VERB_HINTS_JA = {"砕", "殺", "走", "食べ", "行", "来", "言", "思", "作っ"}
SENTENCE_PUNCT = set(".!?。！？")


@dataclass
class TranslationScore:
    provider: str
    text: str
    score: float
    reasons: List[str] = field(default_factory=list)
    penalties: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _tokenish_len(text: str) -> int:
    if not text:
        return 0
    # Spaces for Latin; characters as fallback for CJK-ish text.
    if " " in text.strip():
        return len([x for x in re.split(r"\s+", text.strip()) if x])
    return max(1, len(text.strip()) // 2)


def _contains_source_latin(text: str, target_lang: str) -> bool:
    if canonical_lang(target_lang) in {"ja", "zh", "ko", "ru", "ar", "hi", "th"}:
        return bool(re.search(r"[A-Za-z]{3,}", text or ""))
    return False


def score_translation(
    source_text: str,
    translated_text: str,
    *,
    source_language: str,
    target_language: str,
    provider: str = "unknown",
    mode: str = "prompt",
    dictionary_targets: Optional[Iterable[str]] = None,
) -> TranslationScore:
    src = canonical_lang(source_language)
    tgt = canonical_lang(target_language)
    source = source_text or ""
    text = translated_text or ""
    score = 100.0
    reasons: List[str] = []
    penalties: List[str] = []

    if not text.strip():
        return TranslationScore(provider=provider, text=text, score=0.0, penalties=["empty output"])

    if text.strip() == source.strip() and src != tgt:
        score -= 35
        penalties.append("unchanged from source")

    src_len = max(1, _tokenish_len(source))
    out_len = max(1, _tokenish_len(text))
    ratio = out_len / src_len
    if ratio <= 2.5:
        score += 5
        reasons.append("compact output")
    elif ratio > 4.0:
        score -= 25
        penalties.append(f"large expansion ratio {ratio:.2f}")
    elif ratio > 2.5:
        score -= 10
        penalties.append(f"moderate expansion ratio {ratio:.2f}")

    stripped = text.strip()
    if stripped and stripped[-1] in SENTENCE_PUNCT and mode == "prompt":
        score -= 10
        penalties.append("sentence punctuation in prompt mode")

    lower = stripped.lower()
    for term in HALLUCINATION_TERMS:
        if term.lower() in lower:
            # Do not penalize if source already included it.
            if term.lower() not in source.lower():
                score -= 30
                penalties.append(f"possible hallucinated proper noun: {term}")
                break

    if tgt == "ja" and any(h in stripped for h in BAD_PROMPT_VERB_HINTS_JA):
        score -= 15
        penalties.append("possible added Japanese verb/action")

    script_re = TARGET_SCRIPT_HINTS.get(tgt)
    if script_re:
        if script_re.search(stripped):
            score += 5
            reasons.append("target script detected")
        else:
            score -= 20
            penalties.append("target script not detected")

    if _contains_source_latin(stripped, tgt):
        # Sometimes loanwords are okay, but in automatic scoring this is a mild warning.
        score -= 6
        penalties.append("latin source-like text remains")

    if dictionary_targets:
        targets = [t for t in dictionary_targets if isinstance(t, str) and t.strip()]
        if targets and any(t in stripped for t in targets):
            score += 12
            reasons.append("dictionary/glossary target matched")

    return TranslationScore(
        provider=provider,
        text=text,
        score=max(0.0, min(120.0, round(score, 2))),
        reasons=reasons,
        penalties=penalties,
    )


def choose_best(scores: List[TranslationScore]) -> TranslationScore:
    if not scores:
        return TranslationScore(provider="none", text="", score=0.0, penalties=["no candidates"])
    return sorted(scores, key=lambda s: (-s.score, len(s.text), s.provider))[0]
