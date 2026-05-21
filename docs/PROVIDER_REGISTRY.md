# Provider Registry

Provider implementations should live in:

```text
language/providers/
```

The old top-level `providers/` folder is intentionally removed from the packaged extension to avoid duplicate imports.

Canonical entry point:

```python
from language.providers.provider_registry import PROVIDER_REGISTRY
```

Runtime provider loading should go through `language.translation_providers.get_provider()` so the UI, CLI tests, and extension all use the same implementation.

Currently supported providers shown in normal UI:

- Argos
- NLLB
- Dictionary
- Smart/composite chains

Scaffolded cloud providers can remain in `language/providers/`, but should stay `experimental` until tested.
