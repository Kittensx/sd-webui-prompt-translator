# Project Reorganization

The project is organized as:

```text
language/
  parser/
  translation/
  providers/
  dictionary/
  utils/
  diagnostics/
  ui/
tests/
scripts/
models/
dictionaries/
test_outputs/
docs/
```

Top-level `models/`, `dictionaries/`, and `test_outputs/` are intentional for easier zip exclusion, GitHub releases, and user-managed assets.

Compatibility wrappers remain at `language/*.py` so older imports and commands keep working while code migrates to the modular layout.
