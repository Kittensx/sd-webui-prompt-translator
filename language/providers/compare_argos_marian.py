#!/usr/bin/env python3
"""
compare_argos_marian.py

Side-by-side translation test for Argos Translate and MarianMT.

Examples:
  python compare_argos_marian.py --text "riverbank at golden hour" --source en --target ja --models-dir ./models
  python compare_argos_marian.py --text "桜並木の小道" --source ja --target en --models-dir ./models

Notes:
  - Argos uses its installed package registry. The --models-dir is accepted for symmetry,
    but Argos normally installs packages into its own local package location.
  - Marian looks for local Hugging Face snapshots under --models-dir/marian first, then
    --models-dir, then falls back to a model id if online access is available.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

try:
    from ..paths import MODELS_DIR
except ImportError:
    try:
        from language.paths import MODELS_DIR
    except ImportError:
        from paths import MODELS_DIR

MARIAN_MODEL_IDS = {
    ("en", "ja"): "Helsinki-NLP/opus-mt-en-jap",
    ("ja", "en"): "Helsinki-NLP/opus-mt-ja-en",
    ("en", "es"): "Helsinki-NLP/opus-mt-en-es",
    ("es", "en"): "Helsinki-NLP/opus-mt-es-en",
    ("en", "fr"): "Helsinki-NLP/opus-mt-en-fr",
    ("fr", "en"): "Helsinki-NLP/opus-mt-fr-en",
    ("en", "de"): "Helsinki-NLP/opus-mt-en-de",
    ("de", "en"): "Helsinki-NLP/opus-mt-de-en",
}


def translate_argos(text: str, source: str, target: str) -> tuple[Optional[str], Optional[str]]:
    try:
        import argostranslate.translate as argos_translate
    except Exception as e:
        return None, f"Argos import failed: {e!r}"

    try:
        installed = argos_translate.get_installed_languages()
        src_obj = next((lang for lang in installed if lang.code == source), None)
        tgt_obj = next((lang for lang in installed if lang.code == target), None)
        if src_obj is None:
            return None, f"Argos source language not installed: {source}"
        if tgt_obj is None:
            return None, f"Argos target language not installed: {target}"

        translation = src_obj.get_translation(tgt_obj)
        if translation is None:
            return None, f"Argos pair not installed: {source}->{target}"
        return translation.translate(text), None
    except Exception as e:
        return None, f"Argos translation failed: {e!r}"


def _candidate_marian_dirs(models_dir: Path, source: str, target: str) -> list[Path]:
    names = [
        f"{source}-{target}",
        f"{source}_{target}",
        f"opus-mt-{source}-{target}",
        f"Helsinki-NLP--opus-mt-{source}-{target}",
    ]
    roots = [models_dir / "marian", models_dir]
    out = []
    for root in roots:
        for name in names:
            out.append(root / name)
        if root.exists():
            for p in root.rglob("config.json"):
                out.append(p.parent)
    seen = set()
    unique = []
    for p in out:
        key = str(p.resolve()) if p.exists() else str(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def _find_local_marian_model(models_dir: Path, source: str, target: str) -> Optional[Path]:
    for p in _candidate_marian_dirs(models_dir, source, target):
        if (p / "config.json").exists():
            return p
    return None


def translate_marian(text: str, source: str, target: str, models_dir: Path) -> tuple[Optional[str], Optional[str]]:
    try:
        from transformers import MarianMTModel, MarianTokenizer
    except Exception as e:
        return None, f"Marian/transformers import failed: {e!r}"

    model_path = _find_local_marian_model(models_dir, source, target)
    model_ref = str(model_path) if model_path else MARIAN_MODEL_IDS.get((source, target))
    if not model_ref:
        return None, f"No Marian model mapping known for {source}->{target}. Add it to MARIAN_MODEL_IDS."

    try:
        tokenizer = MarianTokenizer.from_pretrained(model_ref)
        model = MarianMTModel.from_pretrained(model_ref)
        batch = tokenizer([text], return_tensors="pt", padding=True, truncation=True)
        generated = model.generate(**batch)
        return tokenizer.decode(generated[0], skip_special_tokens=True), None
    except Exception as e:
        location_note = f"local/remote model ref: {model_ref}"
        return None, f"Marian translation failed ({location_note}): {e!r}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Side-by-side Argos vs Marian translation test")
    ap.add_argument("--text", required=True, help="Text to translate")
    ap.add_argument("--source", default="en", help="Source language code, e.g. en")
    ap.add_argument("--target", default="ja", help="Target language code, e.g. ja")
    ap.add_argument("--models-dir", default=str(MODELS_DIR), help="Root model folder; Marian checked under models/marian")
    ap.add_argument("--json", action="store_true", help="Print JSON instead of human text")
    args = ap.parse_args()

    models_dir = Path(args.models_dir).expanduser().resolve()

    argos_text, argos_error = translate_argos(args.text, args.source, args.target)
    marian_text, marian_error = translate_marian(args.text, args.source, args.target, models_dir)

    payload = {
        "input": args.text,
        "source_language": args.source,
        "target_language": args.target,
        "models_dir": str(models_dir),
        "argos": {"ok": argos_error is None, "translation": argos_text, "error": argos_error},
        "marian": {"ok": marian_error is None, "translation": marian_text, "error": marian_error},
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Input ({args.source}->{args.target}): {args.text}")
        print("-" * 72)
        print("Argos:")
        print(f"  {argos_text}" if argos_error is None else f"  ERROR: {argos_error}")
        print("Marian:")
        print(f"  {marian_text}" if marian_error is None else f"  ERROR: {marian_error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
# python compare_argos_marian.py --text "riverbank at golden hour" --source en --target ja --models-dir ./models --json