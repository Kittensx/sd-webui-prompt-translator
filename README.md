# Language Extension

Prompt-aware multilingual translation backend for Stable Diffusion workflows.

This project is designed for AI image prompting systems where prompts are not just plain text. Instead of blindly translating strings, the extension uses a parser-aware translation layer that preserves prompt syntax, weights, operators, LoRA tags, semantic blocks, and scheduling structures.

---

# Features

* Prompt-aware translation pipeline
* NLLB provider support
* Argos Translate provider support
* Smart translation routing
* Dictionary and protected-term support
* Parser-safe translation spans
* Semantic prompt block preservation
* Stable Diffusion syntax protection
* Extension-ready install/bootstrap flow
* Provider management system
* Translation cache system
* Modular architecture for future providers

---

# Prompt-Aware Translation

Traditional translators break Stable Diffusion prompts because they treat prompts as normal sentences.

This extension separates:

```python
prompt_parser -> understands syntax
translator    -> translates only text spans
```

The parser identifies which parts are safe to translate.

Example:

```text
(cat:1.2), lake, {утка, озеро, женщина}
```

Becomes:

```text
(猫:1.2), 湖, {アヒル, 湖, 女性}
```

without corrupting:

* weights
* brackets
* syntax
* operators
* grouped prompt structures

---

# Syntax Protection

The parser preserves:

```text
(...)
[...]
{...}
<lora:name:weight>
<embedding:name>
BREAK
AND
weights like :1.2
pipes |
scheduled syntax
alternate/random syntax
semantic %%...%% blocks
```

Translation only occurs on valid text spans.

---

# Architecture

## Core Parser Interface

```python
@dataclass
class PromptSpan:
    kind: str
    value: str
    translatable: bool
```

```python
parse_prompt_for_translation(text) -> list[PromptSpan]
```

This keeps the translation backend decoupled from the parser implementation.

Future versions can directly integrate with a full prompt parser or semantic prompt system.

---

# Providers

Currently supported:

* NLLB
* Argos
* Smart
* Dictionary

Additional providers may exist as scaffolding but are intentionally hidden until validated.

---

# Installation

## A1111 / Forge Extension

Place the extension inside:

```text
stable-diffusion-webui/extensions/
```

Then restart the UI.

The extension bootstrap:

* creates required folders
* installs lightweight dependencies
* initializes cache/config files
* prepares provider directories

---

# Model Installation

See:

```text
docs/INSTALL_MODELS.md
```

for:

* NLLB installation
* Argos model installation
* manual model setup
* provider configuration

Large models are intentionally NOT bundled with the repository.

---

# Folder Structure

```text
language/
├── bootstrap.py
├── prompt_translation_parser.py
├── translation_cache.py
├── provider_model_manager.py
├── translation_providers.py
├── dictionaries/
├── cache/
├── models/
│   ├── nllb/
│   └── argos/
```

---

# Design Goals

* Parser-aware translation
* Non-destructive prompt handling
* Stable Diffusion compatibility
* Modular provider architecture
* Lightweight extension integration
* Portable standalone backend support
* Future semantic prompt integration

---

# Future Plans

* Full semantic prompt parser integration
* Advanced tokenizer-aware translation
* Multi-stage translation pipelines
* Translation quality scoring
* Batch prompt translation
* Automatic provider fallback
* Translation memory improvements
* Additional local/offline providers

---

# Status

Active development.

The project currently focuses on:

* parser-safe translation
* provider stabilization
* model management
* extension integration
* prompt syntax preservation

---

# License

MIT License
