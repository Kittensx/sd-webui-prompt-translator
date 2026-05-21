# Installing translation models

The extension creates folders and installs small Python dependencies on startup, but it does **not** automatically download large translation models. Install models manually from the UI when available, or use the scripts below.

## Folder layout

Expected local folders:

```text
language/models/argos/
language/models/nllb/
language/dictionaries/
language/cache/
language/config/
```

Run the bootstrap manually if the folders are missing:

```bash
python language/bootstrap.py
```

## Argos Translate models

Argos uses per-language-pair packages. Good starter pairs are English to/from Japanese, Spanish, French, German, Korean, and Chinese.

Install the Argos Python dependency:

```bash
python language/provider_model_manager.py install-argos
```

Install one pair:

```bash
python language/provider_model_manager.py install-pair --source-language en --target-language ja --models-dir language/models/argos
```

Install the lightweight recommended Argos bundle:

```bash
python language/provider_model_manager.py install-bundle --bundle lightweight --models-dir language/models/argos
```

Check Argos status:

```bash
python language/provider_model_manager.py matrix --bundle lightweight --update-index
```

Argos package index website:

- https://www.argosopentech.com/argospm/index/

You can also browse the Argos Translate project:

- https://github.com/argosopentech/argos-translate

## NLLB models

NLLB uses one multilingual Hugging Face model instead of separate pair files. Recommended default:

```text
facebook/nllb-200-distilled-600M
```

Install NLLB Python dependencies:

```bash
python language/provider_model_manager.py install-nllb
```

Do **not** use `--include-torch` inside A1111/Forge unless you know you need it. The WebUI usually manages Torch itself.

Download the default NLLB model:

```bash
python language/provider_model_manager.py install-nllb-model --models-dir language/models --model facebook/nllb-200-distilled-600M
```

Check NLLB status:

```bash
python language/provider_model_manager.py nllb-matrix --bundle lightweight --models-dir language/models --model facebook/nllb-200-distilled-600M
```

Hugging Face model pages:

- https://huggingface.co/facebook/nllb-200-distilled-600M
- https://huggingface.co/facebook/nllb-200-distilled-1.3B

For private or gated downloads, set `HF_TOKEN` before running the script:

```bash
set HF_TOKEN=your_token_here
python language/provider_model_manager.py install-nllb-model --models-dir language/models --model facebook/nllb-200-distilled-600M
```

On macOS/Linux:

```bash
export HF_TOKEN=your_token_here
python language/provider_model_manager.py install-nllb-model --models-dir language/models --model facebook/nllb-200-distilled-600M
```

## Dictionary provider

Dictionary mode does not require model downloads. Edit:

```text
language/dictionaries/custom_dictionary.json
language/dictionaries/protected_terms.json
```

Example:

```json
{
  "1girl": "1girl",
  "masterpiece": "masterpiece",
  "BREAK": "BREAK"
}
```

## Recommended first install

For most users:

```bash
python language/bootstrap.py
python language/provider_model_manager.py install-argos
python language/provider_model_manager.py install-bundle --bundle lightweight --models-dir language/models/argos
python language/provider_model_manager.py install-nllb
python language/provider_model_manager.py install-nllb-model --models-dir language/models --model facebook/nllb-200-distilled-600M
```

This gives the extension Argos pair-based translation, NLLB multilingual translation, dictionary overrides, and smart provider fallback support.
