# Testing

Test and diagnostic scripts live in the top-level `tests/` folder. Runtime reports are written to the top-level `test_outputs/` folder.

## Full backend smoke test

```bash
python tests/test_language_backend.py --provider static_dictionary --provider argos --provider nllb --out test_outputs/language_backend_test_report.json
```

Use `--json` for machine-readable output and `--traceback` for full exception traces.

## Prompt-aware roundtrip drift test

```bash
python tests/roundtrip_translation_test.py --providers argos --languages ja fr de --max-prompts 1 --smoke
```

For Argos, missing direct language pairs can be satisfied by installed bridge routes such as `ja -> en -> fr`. To install missing available packages on demand:

```bash
python tests/roundtrip_translation_test.py --providers argos --languages ja fr de --max-prompts 1 --smoke --auto-install-python-deps --auto-install-models --skip-missing-provider-assets
```

Compatibility wrappers remain under `language/`, so older commands like `python language/roundtrip_translation_test.py` still work.
