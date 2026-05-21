# SD WebUI Prompt Translator

Parser-aware multilingual translation backend for Stable Diffusion and AI prompting systems.

Translate prompts without destroying Stable Diffusion syntax, weights, LoRA tags, embeddings, scheduling operators, semantic structures, or prompt composition logic.

---

# Why This Exists

Traditional translators treat prompts like normal sentences.

Stable Diffusion prompts are NOT normal sentences.

Naive translation systems often corrupt:

* prompt weights
* emphasis syntax
* LoRA tags
* embeddings
* prompt operators
* scheduling syntax
* semantic blocks
* tag formatting
* SD-specific terminology

This extension was built specifically for AI image generation workflows.

Instead of blindly translating strings, the system parses prompts into safe translation spans while preserving Stable Diffusion syntax and structure.

---

# Example

## Input

```text
(cat:1.2), masterpiece, {женщина, озеро}, <lora:animeStyle:0.8>
```

## Naive Translation

```text
（猫：1.2）、傑作、{女性、湖}、<ロラ:アニメスタイル:0.8>
```

## Prompt Translator Output

```text
(cat:1.2), masterpiece, {女性, 湖}, <lora:animeStyle:0.8>
```

The extension preserves:

* weights
* syntax
* operators
* LoRA formatting
* embeddings
* prompt structures

while translating only safe text spans.

---

# Features

## Prompt-Aware Translation Pipeline

The parser separates syntax from translatable content.

```text
prompt parser
    ->
protected token layer
    ->
provider translation
    ->
prompt reconstruction
```

Only valid text spans are sent to translation providers.

---

## Protected Token System

Stable Diffusion-specific tokens are automatically protected from accidental translation.

Examples:

```text
masterpiece
best quality
1girl
score_9
BREAK
AND
<lora:model:0.8>
embedding:name
```

Protected tokens bypass providers entirely and are restored during prompt reconstruction.

---

## Dictionary Support

Supports:

* SD tag dictionaries
* user dictionaries
* custom translation overrides
* multilingual dictionaries
* NSFW tag dictionaries
* offline dictionary routing

Dictionary layers can override provider outputs for more Stable Diffusion-friendly translations.

---

## Smart Translation Routing

The backend supports multiple translation providers and routing strategies.

Current providers include:

| Provider     | Offline | Notes                                 |
| ------------ | ------- | ------------------------------------- |
| NLLB         | Yes     | High quality multilingual translation |
| Argos        | Yes     | Lightweight local translation         |
| Dictionary   | Yes     | Rule-based SD tag translation         |
| Smart Router | Hybrid  | Automatically selects providers       |

---

# Syntax Protection

The parser preserves Stable Diffusion structures including:

```text
(cat:1.2)
[de-emphasis]
{grouped prompts}
<lora:model:0.8>
<embedding:name>
BREAK
AND
scheduled prompts
alternate prompts
pipes |
%%semantic blocks%%
```

Translation only occurs on safe text spans.

---

# Architecture

## Core Prompt Span System

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

This architecture keeps the translation system decoupled from parser logic.

The backend is designed for:

* Stable Diffusion
* A1111
* Forge
* ComfyUI
* semantic prompt systems
* future AI prompt pipelines

---

# Modular Provider Architecture

Providers are modular and registry-driven.

The system supports:

* provider plugins
* provider fallback
* provider routing
* cache integration
* future provider expansion

Additional providers may exist as scaffolding but remain hidden until validated.

---

# Installation

## A1111 / Forge Extension

Place the extension inside:

```text
stable-diffusion-webui/extensions/
```

Example:

```text
stable-diffusion-webui/extensions/sd-webui-prompt-translator
```

Then restart the UI.

The bootstrap system automatically:

* creates required folders
* initializes configs
* prepares provider directories
* creates cache storage
* creates protected token storage
* prepares dictionary paths

---

# Model Installation

See:

```text
docs/INSTALL_MODELS.md
```

for:

* NLLB setup
* Argos installation
* offline model configuration
* provider configuration

Large models are intentionally NOT bundled with the repository.

---

# Folder Structure

```text
language/
├── bootstrap/
├── constants/
├── core/
├── dictionaries/
├── models/
├── parser/
├── providers/
├── protected_tokens/
├── routing/
├── services/
├── translation/
├── utils/
└── cache/
```

---

# Design Goals

* parser-aware translation
* Stable Diffusion compatibility
* non-destructive prompt handling
* semantic prompt preservation
* modular provider architecture
* offline/local inference support
* lightweight extension integration
* future semantic prompt compatibility

---

# Current Focus

Current development priorities:

* parser-safe translation
* protected token expansion
* multilingual SD dictionaries
* provider stabilization
* semantic prompt compatibility
* translation quality improvements
* offline inference workflows
* extension integration

---

# Future Plans

Planned future features include:

* semantic parser integration
* tokenizer-aware translation
* multi-stage translation pipelines
* translation quality scoring
* batch translation
* automatic provider fallback
* translation memory improvements
* additional local providers
* ComfyUI integration improvements
* advanced SD tag routing

---

# Status

Active development.

The project is currently transitioning toward a modular AI prompt-language middleware architecture designed for generative AI systems.

---

# License

MIT License
