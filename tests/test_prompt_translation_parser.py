from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from language.parser.prompt_translation_parser import PromptSpan, parse_prompt_for_translation, render_prompt_spans, split_prompt_fragments


def test_top_level_comma_split_ignores_parser_groups():
    text = '♪ cat, lake, ♪ woman from {утка, озеро, женщина}'
    assert split_prompt_fragments(text) == [
        '♪ cat',
        'lake',
        '♪ woman from {утка, озеро, женщина}',
    ]


def test_parser_marks_weights_and_brackets_non_translatable():
    spans = parse_prompt_for_translation('(cat:1.2), lake, {утка, озеро, женщина}')
    assert render_prompt_spans(spans) == '(cat:1.2), lake, {утка, озеро, женщина}'
    assert PromptSpan('operator', '(', False) in spans
    assert PromptSpan('operator', ':1.2', False) in spans
    translatable = [s.value for s in spans if s.translatable]
    assert 'cat' in translatable
    assert ' lake' in translatable or 'lake' in translatable
    assert any('утка' in s for s in translatable)


def test_parser_protects_lora_semantic_and_keywords():
    text = '<lora:test:0.8>, %%semantic cat%% BREAK cat AND dog'
    spans = parse_prompt_for_translation(text)
    assert render_prompt_spans(spans) == text
    protected = [s.value for s in spans if not s.translatable]
    assert '<lora:test:0.8>' in protected
    assert '%%semantic cat%%' in protected
    assert 'BREAK' in protected
    assert 'AND' in protected


def test_parser_protects_scheduled_syntax_v1():
    text = '[cat:dog:0.5], (masterpiece:1.2)'
    spans = parse_prompt_for_translation(text)
    assert render_prompt_spans(spans) == text
    assert any(s.value == 'cat:dog:0.5' and not s.translatable for s in spans)
