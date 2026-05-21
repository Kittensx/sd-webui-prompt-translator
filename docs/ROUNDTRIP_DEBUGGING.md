# Roundtrip test debugging

If roundtrip results show the same input and output for every provider, do not assume the prompt parser protected the whole prompt.

Use the debug provider first:

```bash
python language/roundtrip_translation_test.py --providers debug --max-prompts 1
```

The debug provider prefixes every translatable span. If the output changes, the parser is correctly identifying text spans and the issue is probably provider/model availability, missing Argos packages, silent fallback, or a model returning unchanged output for very short prompt fragments.

The JSON output now includes:

- `prompt_spans`
- `span_results`
- `translatable_span_count`
- `changed_translatable_span_count`
- `no_translatable_span_changed`
- `warning`

For real providers, inspect `span_results`. A row can have translatable spans while still returning unchanged text if the provider does not have the required language pair installed or falls back to the original string.

Recommended smoke tests:

```bash
python language/roundtrip_translation_test.py --providers debug --max-prompts 1
python language/roundtrip_translation_test.py --providers argos --languages ja --max-prompts 1
python language/roundtrip_translation_test.py --providers nllb --languages ja --max-prompts 1
```
