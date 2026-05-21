# Provider Import Debugging

If smoke testing shows:

```text
ModuleNotFoundError("No module named 'providers'")
```

then the translation model has not actually been tested yet. The provider package failed to import before model loading/translation could happen.

This commonly happens when running scripts directly from the extension root like:

```bash
python language/roundtrip_translation_test.py --providers nllb --smoke
```

In that launch mode, Python places `language/` on `sys.path`, not the project root, so root-level `providers/` may not be importable automatically.

The provider loader now adds both paths:

- extension root
- `language/`

and falls back to direct file loading from:

- `providers/<provider>_provider.py`
- `language/providers/<provider>_provider.py`

After this patch, smoke failures should reflect real provider/model issues rather than import-path setup.
