from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from language.parser.prompt_translation_parser import PromptSpan, parse_prompt_for_translation, split_prompt_fragments


@dataclass(frozen=True)
class ProtectedSpan:
    token: str
    value: str


def protect_prompt_parser_spans(value: str) -> Tuple[str, List[ProtectedSpan]]:
    """Compatibility wrapper for the older placeholder API.

    New code should use prompt_translation_parser.parse_prompt_for_translation
    and translate only spans where translatable=True.
    """
    spans = parse_prompt_for_translation(value)
    protected: List[ProtectedSpan] = []
    out: List[str] = []
    for span in spans:
        if span.translatable:
            out.append(span.value)
        elif span.value:
            token = f"__PROMPT_PROTECT_{len(protected)}__"
            protected.append(ProtectedSpan(token=token, value=span.value))
            out.append(token)
    return "".join(out), protected


def restore_prompt_parser_spans(value: str, spans: List[ProtectedSpan]) -> str:
    text = value or ""
    for span in spans:
        text = text.replace(span.token, span.value)
        text = text.replace(span.token.replace("_", " _ "), span.value)
    return text
