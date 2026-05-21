from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Dict, List

from language.utils.language_utils import (
    canonical_lang,
    detect_language_for_values,
    extract_entry_text_fields,
    extract_meta_text_fields,
    normalize_rel_path,
    read_json,
    write_json,
)
from language.translation.translation_cache import TranslationCache
from language.translation.translation_providers import get_provider


def translated_output_path(*, packs_root: Path, source_path: Path, target_language: str, translated_root_name: str = "translated") -> Path:
    rel = source_path.resolve().relative_to(packs_root.resolve())
    return packs_root / translated_root_name / canonical_lang(target_language) / rel


def export_translated_pack(
    *,
    packs_root: Path,
    source_pack: Path | str,
    target_language: str,
    cache_db: Path,
    provider_name: str = "noop",
    out_file: Path | None = None,
    translated_root_name: str = "translated",
    fields: List[str] | None = None,
    translate_meta: bool = True,
) -> Dict[str, Any]:
    packs_root = Path(packs_root).resolve()
    src_path = Path(source_pack)
    if not src_path.is_absolute():
        src_path = packs_root / src_path
    src_path = src_path.resolve()
    data = read_json(src_path)
    if not isinstance(data, dict):
        raise ValueError("Top-level JSON must be an object")

    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    category = str(meta.get("category") or "")
    rel_path = normalize_rel_path(src_path, packs_root)
    target = canonical_lang(target_language)
    source = canonical_lang(meta.get("source_language") or meta.get("pack_language") or "")
    if source == "und":
        all_values: List[str] = []
        for vals in extract_meta_text_fields(meta).values():
            all_values.extend(vals)
        for key, entry in data.items():
            if isinstance(key, str) and not key.startswith("_") and isinstance(entry, dict):
                all_values.append(key)
                for vals in extract_entry_text_fields(entry).values():
                    all_values.extend(vals)
        source, _conf, _scores = detect_language_for_values(all_values)

    provider = get_provider(provider_name)
    cache = TranslationCache(cache_db)
    out = copy.deepcopy(data)
    out_meta = out.get("_meta") if isinstance(out.get("_meta"), dict) else {}

    translated_fields_count = 0
    if translate_meta:
        for field_name, values in extract_meta_text_fields(out_meta).items():
            translated = cache.get_or_create_translation(
                pack_path=rel_path,
                category=category,
                entry_key="<meta>",
                field_name=field_name,
                source_language=source,
                target_language=target,
                source_values=values,
                provider_obj=provider,
            )
            if isinstance(out_meta.get(field_name), list):
                out_meta[field_name] = translated
            elif translated:
                out_meta[field_name] = translated[0]
            translated_fields_count += 1

    out_meta.update({
        "source_language": source,
        "pack_language": target,
        "supported_languages": sorted(set([source, target])),
        "translation_type": "machine" if provider_name not in {"noop", "none"} else "placeholder",
        "translation_provider": getattr(provider, "name", provider_name),
        "translation_of": category,
        "translation_source_path": rel_path,
    })
    out["_meta"] = out_meta

    allowed = set(fields) if fields else None
    for key, entry in list(out.items()):
        if not isinstance(key, str) or key.startswith("_") or not isinstance(entry, dict):
            continue
        entry_fields = extract_entry_text_fields(entry)
        if allowed is not None:
            entry_fields = {k: v for k, v in entry_fields.items() if k in allowed}
        for field_name, values in entry_fields.items():
            translated = cache.get_or_create_translation(
                pack_path=rel_path,
                category=category,
                entry_key=key,
                field_name=field_name,
                source_language=source,
                target_language=target,
                source_values=values,
                provider_obj=provider,
            )
            entry[field_name] = translated
            translated_fields_count += 1

    dest = Path(out_file) if out_file else translated_output_path(
        packs_root=packs_root,
        source_path=src_path,
        target_language=target,
        translated_root_name=translated_root_name,
    )
    write_json(dest, out)
    return {
        "source_pack": rel_path,
        "out_file": str(dest),
        "category": category,
        "source_language": source,
        "target_language": target,
        "translated_fields": translated_fields_count,
        "provider": getattr(provider, "name", provider_name),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Export a full translated mirror pack under translated/<lang>/.")
    ap.add_argument("--packs-root", required=True, type=Path)
    ap.add_argument("--source-pack", required=True)
    ap.add_argument("--target-language", required=True)
    ap.add_argument("--cache-db", required=True, type=Path)
    ap.add_argument("--provider", default="noop")
    ap.add_argument("--out-file", type=Path, default=None)
    ap.add_argument("--translated-root-name", default="translated")
    ap.add_argument("--fields", default="tags,aliases,search_tags,negative")
    ap.add_argument("--skip-meta", action="store_true")
    args = ap.parse_args()

    fields = [x.strip() for x in args.fields.split(",") if x.strip()] if args.fields else None
    payload = export_translated_pack(
        packs_root=args.packs_root,
        source_pack=args.source_pack,
        target_language=args.target_language,
        cache_db=args.cache_db,
        provider_name=args.provider,
        out_file=args.out_file,
        translated_root_name=args.translated_root_name,
        fields=fields,
        translate_meta=not bool(args.skip_meta),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
