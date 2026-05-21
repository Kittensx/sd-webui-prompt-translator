from __future__ import annotations

"""
Compare multiple translation providers, score their outputs, and pick a winner.

Default provider set for this project:
  static_dictionary -> argos -> nllb

Marian is intentionally not included in official defaults because prompt-fragment
translation tests showed high hallucination risk. Users can still write external
provider plugins if they want it.
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

try:
    from ..paths import MODELS_DIR
except ImportError:
    try:
        from language.paths import MODELS_DIR
    except ImportError:
        from paths import MODELS_DIR
from typing import Dict, List, Sequence

try:
    from language.translation.translation_providers import get_provider
    from language.translation.translation_quality import choose_best, score_translation
except Exception:
    from language.translation.translation_providers import get_provider
    from .translation_quality import choose_best, score_translation

DEFAULT_COMPARE_PROVIDERS = ["static_dictionary", "argos", "nllb"]


def translate_with_provider(provider_name: str, text: str, source_language: str, target_language: str, **kwargs) -> Dict[str, object]:
    try:
        provider = get_provider(provider_name, **kwargs)
        translated = provider.translate_texts([text], source_language=source_language, target_language=target_language)[0]
        return {"provider": provider_name, "ok": True, "translation": translated, "error": None}
    except Exception as e:
        return {"provider": provider_name, "ok": False, "translation": None, "error": repr(e)}


def smart_translate_text(
    text: str,
    *,
    source_language: str,
    target_language: str,
    providers: Sequence[str] | None = None,
    models_dir: str | Path = MODELS_DIR,
    dictionary_paths: Sequence[str | Path] | None = None,
    mode: str = "prompt",
) -> Dict[str, object]:
    providers = list(providers or DEFAULT_COMPARE_PROVIDERS)
    raw_results = []
    scored = []
    kwargs = {"models_dir": str(models_dir), "dictionary_paths": list(dictionary_paths or [])}

    for name in providers:
        res = translate_with_provider(name, text, source_language, target_language, **kwargs)
        raw_results.append(res)
        if res.get("ok") and isinstance(res.get("translation"), str):
            scored.append(score_translation(
                text,
                str(res["translation"]),
                source_language=source_language,
                target_language=target_language,
                provider=name,
                mode=mode,
            ))

    winner = choose_best(scored)
    return {
        "input": text,
        "source_language": source_language,
        "target_language": target_language,
        "mode": mode,
        "winner": winner.to_dict(),
        "candidates": [s.to_dict() for s in sorted(scored, key=lambda x: -x.score)],
        "raw_results": raw_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prompt-aware provider comparison and translation chooser.")
    parser.add_argument("--text", required=True)
    parser.add_argument("--source", default="en")
    parser.add_argument("--target", default="ja")
    parser.add_argument("--models-dir", default=str(MODELS_DIR))
    parser.add_argument("--provider", action="append", default=None, help="Provider to compare. Can be repeated. Default: dict, argos, nllb")
    parser.add_argument("--dictionary", action="append", default=[])
    parser.add_argument("--mode", choices=["prompt", "natural_language", "search"], default="prompt")
    args = parser.parse_args()

    result = smart_translate_text(
        args.text,
        source_language=args.source,
        target_language=args.target,
        providers=args.provider or DEFAULT_COMPARE_PROVIDERS,
        models_dir=args.models_dir,
        dictionary_paths=args.dictionary,
        mode=args.mode,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
