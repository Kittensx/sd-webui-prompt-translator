from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence



@dataclass(frozen=True)
class PromptSpan:
    kind: str          # text | protected | separator | operator
    value: str
    translatable: bool = False


_OPEN_TO_CLOSE = {"(": ")", "[": "]", "{": "}"}
_CLOSE_TO_OPEN = {")": "(", "]": "[", "}": "{"}
_WEIGHT_RE_CHARS = set("+-0123456789.")


def parse_prompt_for_translation(text: str, *, translate_semantic_blocks: bool = False) -> List[PromptSpan]:
    """Lightweight prompt-aware tokenizer for machine translation.

    This is intentionally an adapter layer, not the final prompt parser. It
    preserves parser syntax as non-translatable spans and marks only natural
    language text spans as translatable. Later, semantic_prompt/prompt_parser can
    replace this function while keeping the translator contract stable.
    """
    spans = _parse_region(text or "", stop_chars=None, translate_semantic_blocks=translate_semantic_blocks)
    # Whitespace is formatting, not semantic text. Keeping it non-translatable
    # avoids pointless provider calls and cleaner diagnostics.
    return [
        PromptSpan(span.kind, span.value, False)
        if span.kind == "text" and not span.value.strip()
        else span
        for span in spans
    ]


def split_prompt_fragments(text: str) -> List[str]:
    """Split an A1111-style prompt on top-level commas only."""
    parts: List[str] = []
    start = 0
    stack: List[str] = []
    quote = ""
    escaped = False
    in_regex = False
    s = text or ""
    for i, ch in enumerate(s):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in {"'", '"'}:
            quote = ch
            continue
        if in_regex:
            if ch == "/":
                in_regex = False
            continue
        if ch == "/" and _looks_like_regex_start(s, i):
            in_regex = True
            continue
        if ch in _OPEN_TO_CLOSE:
            stack.append(ch)
            continue
        if ch in _CLOSE_TO_OPEN:
            if stack and stack[-1] == _CLOSE_TO_OPEN[ch]:
                stack.pop()
            continue
        if ch == "," and not stack:
            part = s[start:i].strip()
            if part:
                parts.append(part)
            start = i + 1
    tail = s[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def render_prompt_spans(spans: Sequence[PromptSpan]) -> str:
    return "".join(span.value for span in spans)


def _parse_region(text: str, *, stop_chars: set[str] | None, translate_semantic_blocks: bool) -> List[PromptSpan]:
    spans: List[PromptSpan] = []
    buf: List[str] = []
    i = 0

    def flush_text() -> None:
        if buf:
            text_value = "".join(buf)
            spans.append(PromptSpan("text", text_value, True))
            buf.clear()

    while i < len(text):
        ch = text[i]
        if stop_chars and ch in stop_chars:
            break

        if text.startswith("%%", i):
            end = text.find("%%", i + 2)
            if end != -1:
                flush_text()
                block = text[i:end + 2]
                kind = "text" if translate_semantic_blocks else "protected"
                spans.append(PromptSpan(kind, block, translate_semantic_blocks))
                i = end + 2
                continue

        if ch == "<":
            end = text.find(">", i + 1)
            if end != -1 and _is_angle_tag(text[i:end + 1]):
                flush_text()
                spans.append(PromptSpan("protected", text[i:end + 1], False))
                i = end + 1
                continue

        if ch == "/" and _looks_like_regex_start(text, i):
            end = _find_regex_end(text, i)
            if end > i:
                flush_text()
                spans.append(PromptSpan("protected", text[i:end + 1], False))
                i = end + 1
                continue

        word = _read_word(text, i)
        if word in {"BREAK", "AND"} and _word_is_standalone(text, i, i + len(word)):
            flush_text()
            spans.append(PromptSpan("operator", word, False))
            i += len(word)
            continue

        if ch in _OPEN_TO_CLOSE:
            end = _find_balanced_end(text, i)
            if end > i:
                flush_text()
                spans.append(PromptSpan("operator", ch, False))
                inner = text[i + 1:end]
                if _should_protect_whole_group(ch, inner):
                    spans.append(PromptSpan("protected", inner, False))
                else:
                    spans.extend(_parse_group_inner(inner, translate_semantic_blocks=translate_semantic_blocks))
                spans.append(PromptSpan("operator", _OPEN_TO_CLOSE[ch], False))
                i = end + 1
                continue

        if ch in {",", "|"}:
            flush_text()
            spans.append(PromptSpan("separator", ch, False))
            i += 1
            continue

        buf.append(ch)
        i += 1

    flush_text()
    return _coalesce_text_spans(spans)


def _parse_group_inner(inner: str, *, translate_semantic_blocks: bool) -> List[PromptSpan]:
    spans: List[PromptSpan] = []
    part_start = 0
    for colon in _top_level_colons(inner):
        suffix = inner[colon + 1:]
        if _is_weight_suffix(suffix):
            if colon > part_start:
                spans.extend(_parse_region(inner[part_start:colon], stop_chars=None, translate_semantic_blocks=translate_semantic_blocks))
            spans.append(PromptSpan("operator", inner[colon:], False))
            return spans
    return _parse_region(inner, stop_chars=None, translate_semantic_blocks=translate_semantic_blocks)


def _should_protect_whole_group(open_ch: str, inner: str) -> bool:
    stripped = inner.strip()
    if not stripped:
        return False
    # Scheduled syntax is parser-sensitive. Keep it unchanged for V1.
    if open_ch == "[" and len(_top_level_colons(inner)) >= 2:
        return True
    # Regex-like or wildcard-heavy groups are safer protected until the real parser owns this.
    if any(c in inner for c in ("/", "\\", "^", "$")):
        return True
    return False


def _top_level_colons(text: str) -> List[int]:
    positions: List[int] = []
    stack: List[str] = []
    quote = ""
    escaped = False
    for i, ch in enumerate(text):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in {"'", '"'}:
            quote = ch
            continue
        if ch in _OPEN_TO_CLOSE:
            stack.append(ch)
            continue
        if ch in _CLOSE_TO_OPEN:
            if stack and stack[-1] == _CLOSE_TO_OPEN[ch]:
                stack.pop()
            continue
        if ch == ":" and not stack:
            positions.append(i)
    return positions


def _is_weight_suffix(value: str) -> bool:
    s = value.strip()
    if not s:
        return False
    return all(c in _WEIGHT_RE_CHARS for c in s) and any(c.isdigit() for c in s)


def _is_angle_tag(span: str) -> bool:
    low = span.lower()
    return low.startswith("<lora:") or low.startswith("<lyco:") or low.startswith("<embedding:") or low.startswith("<hypernet:")


def _read_word(text: str, pos: int) -> str:
    j = pos
    while j < len(text) and (text[j].isalpha() or text[j] == "_"):
        j += 1
    return text[pos:j]


def _word_is_standalone(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start > 0 else " "
    after = text[end] if end < len(text) else " "
    return not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_")


def _find_balanced_end(text: str, start: int) -> int:
    stack = [text[start]]
    quote = ""
    escaped = False
    for i in range(start + 1, len(text)):
        ch = text[i]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in {"'", '"'}:
            quote = ch
            continue
        if ch in _OPEN_TO_CLOSE:
            stack.append(ch)
            continue
        if ch in _CLOSE_TO_OPEN and stack and stack[-1] == _CLOSE_TO_OPEN[ch]:
            stack.pop()
            if not stack:
                return i
    return -1


def _looks_like_regex_start(text: str, pos: int) -> bool:
    prev = text[pos - 1] if pos > 0 else " "
    if prev not in " \t\n([{:=,!":
        return False
    end = _find_regex_end(text, pos)
    if end <= pos + 1:
        return False
    body = text[pos + 1:end]
    return any(c in body for c in ".*+?[]{}|^$\\")


def _find_regex_end(text: str, start: int) -> int:
    escaped = False
    for i in range(start + 1, len(text)):
        ch = text[i]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "/":
            j = i + 1
            while j < len(text) and text[j].isalpha():
                j += 1
            return j - 1
    return -1


def _coalesce_text_spans(spans: Sequence[PromptSpan]) -> List[PromptSpan]:
    out: List[PromptSpan] = []
    for span in spans:
        if out and span.kind == "text" and out[-1].kind == "text" and span.translatable == out[-1].translatable:
            prev = out[-1]
            out[-1] = PromptSpan(prev.kind, prev.value + span.value, prev.translatable)
        else:
            out.append(span)
    return out
