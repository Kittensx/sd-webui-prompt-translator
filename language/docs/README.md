# Semantic Prompt Pack Language Backend

This folder is a backend scaffold for multilingual pack search, runtime translation, and optional full-pack translation export.

## Design

- Source pack JSON files stay canonical and small.
- Runtime translations are stored in SQLite, keyed by `pack_path + entry_key + field_name + source/target language + source_hash`.
- Query translation is cached separately.
- Full translated packs are optional exports under `packs/translated/<lang>/...`.
- Native non-English packs should stay under `packs/language/<lang>/...`.

## Core files

- `language_utils.py` - language code normalization, lightweight detection, pack text extraction helpers.
- `translation_cache.py` - SQLite cache tables for translated lines and language metadata.
- `translation_providers.py` - provider interface plus noop/debug/static dictionary providers.
- `build_language_index.py` - scans packs and writes language metadata to JSON and/or SQLite.
- `multilingual_search.py` - detects query language, translates query to canonical language, and searches normal pack catalogue.
- `translate_entry.py` - translates only one matched entry and stores the translated fields in cache.
- `export_translated_pack.py` - optional full-pack mirror export into `translated/<lang>/`.
- `cache_maintenance.py` - cache stats utility.

## Recommended folder policy

```text
packs/language/<lang>/...     Native authored language packs
packs/translated/<lang>/...   User-requested full translated mirror packs
semantic/cache/...            Runtime translation cache DB
```

## Example commands

Build language index/cache:

```bash
python build_language_index.py --packs-root ./packs --out-json ./pack_language.index.json --cache-db ./semantic/cache/pack_language.sqlite
```

Search with translated query fallback:

```bash
python multilingual_search.py "川岸" --packs-root ./packs --pack-search-engine ./pack_search_engine.py --cache-db ./semantic/cache/pack_language.sqlite --provider static_dictionary
```

Translate only the matched entry:

```bash
python translate_entry.py --packs-root ./packs --pack-path environment/water/river.json --entry-key riverbank --target-language ja --cache-db ./semantic/cache/pack_language.sqlite --provider static_dictionary
```

Export a translated full-pack mirror:

```bash
python export_translated_pack.py --packs-root ./packs --source-pack environment/water/river.json --target-language ja --cache-db ./semantic/cache/pack_language.sqlite --provider static_dictionary
```

## Integration notes

A1111 extension UI can call these layers in order:

1. Detect query language.
2. Translate query to canonical language if needed.
3. Search normal catalogue.
4. Translate only selected output fields when the user asks for a target prompt language.
5. Cache translated lines by source hash.

A future pack-manager app can use the same backend for pack language audit, pack authoring, bundle export, and optional full-pack translation.

## User search cache

`search_cache.py` is a separate cache layer for searches typed by users. It stores final search payloads and lightweight history only. It does not store complete pack files, pack headers, or full pack entries.

Recommended DB location:

```text
semantic/cache/search_cache.sqlite
```

You may also point it at the same SQLite file used by `TranslationCache`; the tables are separate. A separate DB is cleaner for user-facing cache controls.

### Search cache CLI

```bash
python search_cache.py --db ./semantic/cache/search_cache.sqlite stats
python search_cache.py --db ./semantic/cache/search_cache.sqlite list --limit 20
python search_cache.py --db ./semantic/cache/search_cache.sqlite list --history --limit 20
python search_cache.py --db ./semantic/cache/search_cache.sqlite purge-expired
python search_cache.py --db ./semantic/cache/search_cache.sqlite purge-older-than --days 30 --include-history
python search_cache.py --db ./semantic/cache/search_cache.sqlite enforce-limits --max-rows 5000 --max-bytes 52428800
python search_cache.py --db ./semantic/cache/search_cache.sqlite clear --include-history
```

### Integrating with `multilingual_search.py`

Pass `--search-cache-db` when searching:

```bash
python multilingual_search.py "川岸" \
  --packs-root ./packs \
  --pack-search-engine ./pack_search_engine.py \
  --cache-db ./semantic/cache/pack_language.sqlite \
  --search-cache-db ./semantic/cache/search_cache.sqlite \
  --provider static_dictionary \
  --search-cache-ttl-days 30 \
  --search-cache-max-rows 5000 \
  --search-cache-max-bytes 52428800
```

On the first search, `search_cache.hit` is false. On repeated identical searches with the same search settings, `search_cache.hit` is true.

### App / A1111 integration pattern

```python
from pathlib import Path
from pack_lang_backend.multilingual_search import multilingual_search

payload = multilingual_search(
    query=user_query,
    packs_root=Path("semantic/packs"),
    pack_search_engine_path=Path("semantic/tools/pack_search_engine.py"),
    cache_db=Path("semantic/cache/pack_language.sqlite"),
    search_cache_db=Path("semantic/cache/search_cache.sqlite"),
    provider_name="static_dictionary",
    canonical_language="en",
    max_results=25,
    preset="broad",
    display_format="equals",
    catalog_fingerprint=current_catalog_hash,
)
```

Use `catalog_fingerprint` when available. It can be a DB updated timestamp, a pack index hash, or the generated pack language index hash. This prevents old search results from being reused after packs change.

### UI controls to expose

Suggested controls for the future pack-manager app or A1111 panel:

- Enable search cache
- Search cache TTL in days
- Max cached searches
- Max cache size in MB
- Clear cached search results
- Clear search history
- Delete cached searches older than N days
- Purge expired searches
- Pin/unpin selected cache entries

### What the search cache stores

It stores:

- query text
- normalized query
- detected query language
- canonical language
- provider name
- search context/settings
- final result payload JSON
- result count
- byte size
- hit count
- timestamps
- optional history rows

It does not store source pack JSON or translated pack data. Translation lines remain in `translation_cache.py`; search results remain in `search_cache.py`.

## Translation provider plugins

The language backend does not translate by itself. It routes text to a selected provider, then stores results in the translation cache. Providers are optional plugins.

Recommended default chain:

```text
static dictionary -> Argos offline -> optional cloud provider -> fallback original text
```

Available provider names:

```text
noop
prefix_debug / debug
static_dictionary / dict
argos
deepl
openai
google_cloud
dict+argos
```

### Offline Argos provider

Argos is the recommended privacy-first provider. It runs locally and does not send prompt text to a server.

Install optional dependency:

```bash
pip install argostranslate
```

Then install Argos language packages using Argos tooling or your future app UI. The provider intentionally does not auto-download language packages.

Smoke test:

```bash
python provider_test.py --provider argos --source-language en --target-language ja --text riverbank
```

Use in entry translation:

```bash
python translate_entry.py \
  --packs-root ./semantic/packs \
  --pack-path environment/water/river.json \
  --entry-key riverbank \
  --source-language en \
  --target-language ja \
  --cache-db ./semantic/cache/translation_cache.sqlite \
  --provider argos
```

### Optional cloud providers

Cloud providers are disabled unless selected by the user. API keys should come from environment variables, not source files.

DeepL:

```bash
set DEEPL_API_KEY=your_key_here
python provider_test.py --provider deepl --source-language en --target-language ja --text riverbank
```

OpenAI:

```bash
set OPENAI_API_KEY=your_key_here
set OPENAI_TRANSLATION_MODEL=gpt-4.1-mini
python provider_test.py --provider openai --source-language en --target-language ja --text riverbank
```

Google Cloud:

```bash
set GOOGLE_TRANSLATE_API_KEY=your_key_here
python provider_test.py --provider google_cloud --source-language en --target-language ja --text riverbank
```

### App/plugin integration idea

For a pack manager app, expose providers as a settings panel:

```text
Translation provider: [Offline Argos]
Cloud fallback: [Disabled]
Dictionary folder: semantic/language/dictionaries
Cache translations: [On]
Show privacy warning for cloud providers: [On]
```

For A1111 panels, call `get_provider(selected_provider)` and keep the selected provider name in user settings. Do not store API keys in pack JSON.

## Provider/model installation manager

`provider_model_manager.py` adds app-facing provider setup helpers. It does not bundle large model binaries. Instead it defines recommended language bundles and gives your app or A1111 panel functions/CLI commands to install optional dependencies and selected Argos language models after the user chooses them.

Recommended folders:

```text
semantic/
  language/
    dictionaries/
    models/
      argos/
    cache/
    config/
```

### Recommended bundled language metadata

The manager defines an 18-language common set:

```text
en, ja, es, fr, de, it, pt, ko, zh, ru, ar, hi, nl, pl, tr, id, vi, th
```

This is metadata only. The app can show these as a starter bundle. The actual Argos model files are still downloaded only when the user clicks install.

Two bundle presets are available:

```text
lightweight: en<->ja, en<->es, en<->fr, en<->de, en<->ko, en<->zh
full: English pivot pairs for all 18 common languages
```

### CLI examples

Check Argos install status and installed pairs:

```bash
python provider_model_manager.py status
```

Show the starter install matrix:

```bash
python provider_model_manager.py matrix --bundle lightweight --update-index
```

Install Argos itself:

```bash
python provider_model_manager.py install-argos
```

Install one language pair:

```bash
python provider_model_manager.py install-pair \
  --source-language en \
  --target-language ja \
  --models-dir ./semantic/language/models/argos
```

Install the lightweight starter bundle:

```bash
python provider_model_manager.py install-bundle \
  --bundle lightweight \
  --models-dir ./semantic/language/models/argos
```

Write a provider config template:

```bash
python provider_model_manager.py write-config \
  --out ./semantic/language/config/providers.json
```

### App integration

Use these functions from a Pack Manager or Language Manager UI:

```python
from provider_model_manager import (
    check_argos_dependency,
    get_recommended_pairs,
    get_argos_package_matrix,
    install_argos_dependency,
    install_argos_language_bundle,
    install_argos_language_pair,
)

status = check_argos_dependency()

# Show this matrix in a UI table.
matrix = get_argos_package_matrix(
    get_recommended_pairs("lightweight"),
    update_index=True,
)

# Only run this after explicit user approval.
install_argos_dependency()

# Only run this after explicit user approval.
install_argos_language_bundle(
    get_recommended_pairs("lightweight"),
    install_dir="./semantic/language/models/argos",
)
```

### A1111 panel integration

Add a Language Manager accordion with buttons like:

```text
Check Argos Status
Install Argos Provider
Refresh Available Models
Install Selected Language Pair
Install Starter Bundle
Open Language Cache Folder
```

The Gradio button callbacks should call `provider_model_manager.py` functions directly. Do not run installers automatically on startup.

### Provider behavior after install

The Argos provider now exposes:

```python
provider.is_available()
provider.installed_pairs()
provider.supports_pair("en", "ja")
```

Translation calls still flow through the same cache-aware modules:

```text
static dictionary -> Argos offline -> optional cloud fallback -> cache result
```

So model installation is separate from translation use. This keeps the app lightweight while still making common languages easy to install.

## Marian / Hugging Face provider install

Marian is handled differently than Argos. Argos installs `.argosmodel` packages through the Argos package API. Marian uses Hugging Face model repositories, so the app downloads each model repo into an app-managed local folder.

Recommended folders:

```text
semantic/language/models/argos/
semantic/language/models/marian/
```

Install dependencies:

```bash
python provider_model_manager.py install-marian
```

Show install matrix:

```bash
python provider_model_manager.py marian-matrix --bundle lightweight --models-dir ./semantic/language/models/marian
```

Install one Marian model pair:

```bash
python provider_model_manager.py install-marian-pair --source-language en --target-language ja --models-dir ./semantic/language/models/marian
```

Install the lightweight Marian bundle:

```bash
python provider_model_manager.py install-marian-bundle --bundle lightweight --models-dir ./semantic/language/models/marian
```

Use Marian as a provider:

```bash
python translate_entry.py --provider marian --models-dir ./semantic/language/models/marian ...
```

In code:

```python
from translation_providers import get_provider

provider = get_provider(
    "marian",
    models_dir="semantic/language/models/marian",
    allow_remote=False,
)
```

Keep `allow_remote=False` for privacy/offline behavior. Install models first with `provider_model_manager.py`. If set to `True`, Transformers may download missing models from Hugging Face at runtime.

Notes:

- `install-marian` installs `transformers`, `sentencepiece`, and `huggingface_hub` only.
- It intentionally does not install PyTorch because A1111 usually already has a specific Torch/CUDA setup.
- Marian models are larger than dictionary entries and can be larger than some Argos pairs, so expose them as optional downloads in the app UI.

---

## Update: official offline provider stack

Based on prompt-fragment translation testing, the official offline stack is now:

```text
static_dictionary -> Argos -> NLLB
```

Marian is intentionally not included in the official provider list anymore because it produced hallucinated prompt fragments during testing, for example adding named places and actions that were not present in the source text. Users can still add Marian as a separate community/user provider plugin if they want, but it should not be part of the default package.

## NLLB install and test

Install dependencies:

```bash
python provider_model_manager.py install-nllb
```

This installs:

```text
transformers
sentencepiece
huggingface_hub
```

It does not install Torch by default because A1111 usually already has a CUDA-specific Torch install. If you are outside A1111 and need Torch too:

```bash
python provider_model_manager.py install-nllb --include-torch
```

Download the default NLLB model:

```bash
python provider_model_manager.py install-nllb-model --models-dir ./models
```

Or install it as the language backend bundle model:

```bash
python provider_model_manager.py install-nllb-bundle --bundle lightweight --models-dir ./models
```

If Hugging Face needs authentication, set `HF_TOKEN` in the environment before running the installer.

PowerShell:

```powershell
$env:HF_TOKEN="hf_your_token_here"
```

CMD:

```cmd
set HF_TOKEN=hf_your_token_here
```

## Prompt-aware translation chooser

Use `smart_translate.py` to compare providers and pick the best result automatically:

```bash
python smart_translate.py --text "riverbank at golden hour" --source en --target ja --models-dir ./models
```

Default comparison:

```text
static_dictionary
argos
nllb
```

The scorer rewards compact, literal, target-script output and penalizes common prompt translation failures:

```text
hallucinated proper nouns
unexpected sentence punctuation
large expansion
added verbs/actions
wrong target script
unchanged source text
```

Example output shape:

```json
{
  "winner": {
    "provider": "nllb",
    "text": "黄金時に川岸",
    "score": 110.0
  },
  "candidates": []
}
```

## Provider manager commands

Argos:

```bash
python provider_model_manager.py install-argos
python provider_model_manager.py install-bundle --bundle lightweight --models-dir ./models/argos
```

NLLB:

```bash
python provider_model_manager.py install-nllb
python provider_model_manager.py install-nllb-model --models-dir ./models
python provider_model_manager.py nllb-matrix --bundle lightweight --models-dir ./models
```

Provider config template:

```bash
python provider_model_manager.py write-config --out ./providers.template.json
```

## App integration recommendation

For user-facing apps and A1111 panels:

1. Use `provider_model_manager.py status` to show installed provider status.
2. Let users install Argos and/or NLLB explicitly.
3. Use `smart_translate_text()` for automatic provider comparison.
4. Cache the chosen winner, not every candidate, unless the user enables debug/history.
5. Let users manually override a bad translation and store it as a dictionary/glossary entry.


## Provider constructor compatibility fix

`smart_translate.py` passes shared app context such as `models_dir` and `dictionary_paths` into `get_provider()`. The provider factory filters those options per provider constructor, so Argos will not receive `models_dir`, and NLLB will not receive `dictionary_paths`. This keeps optional providers loosely coupled and avoids startup/runtime errors when comparing multiple providers side by side.

## Resilient full backend test runner

Use `test_language_backend.py` when you want to test the whole language backend without stopping on the first failure. This is useful because Argos, NLLB, cloud providers, dictionaries, and cache files are all optional/user-configured.

Basic smoke test:

```bash
python test_language_backend.py --models-dir ./models
```

JSON report:

```bash
python test_language_backend.py --models-dir ./models --json --out ./language_backend_test_report.json
```

Test selected providers only:

```bash
python test_language_backend.py --models-dir ./models --provider argos --provider nllb
```

With a persistent cache DB:

```bash
python test_language_backend.py --models-dir ./models --cache-db ./semantic/language/cache/language_test.sqlite
```

The runner always continues after individual failures and exits with status code 0. Check the `summary.failed` field in the JSON report when you want to gate a release.
