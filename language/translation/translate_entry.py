from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from language.utils.language_utils import (
    canonical_lang,
    detect_language_for_values,
    extract_entry_text_fields,
    normalize_rel_path,
    read_json,
)
from language.translation.translation_cache import TranslationCache
from language.translation.translation_providers import get_provider


def translate_entry(
    *,
    packs_root: Path,
    pack_path: str | Path,
    entry_key: str,
    target_language: str,
    cache_db: Path,
    provider_name: str = "noop",
    source_language: str | None = None,
    fields: List[str] | None = None,
) -> Dict[str, Any]:
    packs_root = Path(packs_root).resolve()
    path = Path(pack_path)
    if not path.is_absolute():
        path = packs_root / path
    data = read_json(path)
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    category = str(meta.get("category") or "")
    entry = data.get(entry_key)
    if not isinstance(entry, dict):
        raise KeyError(f"Entry key not found or not an object: {entry_key}")

    rel_path = normalize_rel_path(path, packs_root)
    target = canonical_lang(target_language)
    source = canonical_lang(source_language or meta.get("source_language") or meta.get("pack_language") or "")

    entry_fields = extract_entry_text_fields(entry)
    if fields:
        allowed = set(fields)
        entry_fields = {k: v for k, v in entry_fields.items() if k in allowed}

    if source == "und":
        values = [entry_key]
        for v in entry_fields.values():
            values.extend(v)
        source, _conf, _scores = detect_language_for_values(values)

    provider = get_provider(provider_name)
    cache = TranslationCache(cache_db)
    translated_fields: Dict[str, List[str]] = {}
    for field_name, values in entry_fields.items():
        translated_fields[field_name] = cache.get_or_create_translation(
            pack_path=rel_path,
            category=category,
            entry_key=entry_key,
            field_name=field_name,
            source_language=source,
            target_language=target,
            source_values=values,
            provider_obj=provider,
        )

    return {
        "pack_path": rel_path,
        "category": category,
        "entry_key": entry_key,
        "source_language": source,
        "target_language": target,
        "provider": getattr(provider, "name", provider_name),
        "translated_fields": translated_fields,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Translate one pack entry into a target language using cache.")
    ap.add_argument("--packs-root", required=True, type=Path)
    ap.add_argument("--pack-path", required=True)
    ap.add_argument("--entry-key", required=True)
    ap.add_argument("--target-language", required=True)
    ap.add_argument("--source-language", default=None)
    ap.add_argument("--cache-db", required=True, type=Path)
    ap.add_argument("--provider", default="noop", help="Provider name: noop, debug, static_dictionary, argos, deepl, openai, google_cloud, dict+argos")
    ap.add_argument("--fields", default="tags,aliases,search_tags,negative")
    args = ap.parse_args()

    fields = [x.strip() for x in args.fields.split(",") if x.strip()] if args.fields else None
    payload = translate_entry(
        packs_root=args.packs_root,
        pack_path=args.pack_path,
        entry_key=args.entry_key,
        target_language=args.target_language,
        cache_db=args.cache_db,
        provider_name=args.provider,
        source_language=args.source_language,
        fields=fields,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
