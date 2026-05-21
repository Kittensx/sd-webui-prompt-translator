from prompt_parser_protection import split_prompt_fragments, protect_prompt_parser_spans, restore_prompt_parser_spans


def test_top_level_comma_split_ignores_parser_groups():
    text = '♪ cat, lake, ♪ woman from {утка, озеро, женщина}'
    assert split_prompt_fragments(text) == [
        '♪ cat',
        'lake',
        '♪ woman from {утка, озеро, женщина}',
    ]


def test_protects_regex_and_balanced_parser_spans():
    text = 'find /cat|lake|woman/i near [from:to:0.5] and (masterpiece:1.2)'
    protected, spans = protect_prompt_parser_spans(text)
    assert '/cat|lake|woman/i' not in protected
    assert '[from:to:0.5]' not in protected
    assert '(masterpiece:1.2)' not in protected
    assert restore_prompt_parser_spans(protected, spans) == text


def test_quotes_do_not_split():
    assert split_prompt_fragments('a, "b, c", {x, y|z}') == ['a', '"b, c"', '{x, y|z}']
