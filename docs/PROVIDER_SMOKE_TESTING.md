# Provider Smoke Testing

Use smoke tests to separate parser problems from provider/model problems.

The prompt parser can be correct while a provider still returns unchanged text because a model is missing, a language pair is unsupported, or a cached provider instance was initialized before models were installed.

## Quick test

```bash
python language/roundtrip_translation_test.py --providers argos --max-prompts 1 --smoke
```

For NLLB:

```bash
python language/roundtrip_translation_test.py --providers nllb --max-prompts 1 --smoke
```

## After installing or moving models

Clear cached provider instances so the next run reloads provider state:

```bash
python language/roundtrip_translation_test.py --providers nllb --max-prompts 1 --smoke --clear-provider-cache
```

This does not mean models should reload for every span. The intended behavior is:

1. Clear cache after model/config changes.
2. Run one direct smoke translation, such as `cat` from English to Japanese.
3. Reuse the initialized provider/model for the full prompt test.

## Interpreting output

If smoke test returns changed text, parser/provider plumbing is working.

If smoke test returns unchanged text with `provider_returned_identical_text`, check:

- model path
- installed Argos language pairs
- NLLB model directory
- source/target language codes
- provider errors in JSON output

If smoke test changes text but prompt roundtrip does not, inspect `prompt_spans` and `span_results` in the JSON output.
