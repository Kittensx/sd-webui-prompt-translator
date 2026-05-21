from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from language_utils import (
    as_list_str,
    canonical_lang,
    dedupe_preserve_order,
    detect_language_for_values,
    extract_entry_text_fields,
    extract_meta_text_fields,
    iter_pack_files,
    normalize_rel_path,
    read_json,
    write_json,
)
from translation_cache import TranslationCache


def infer_source_language_from_path(rel_path: str) -> str | None:
    parts = Path(rel_path).parts
    lowered = [p.lower() for p in parts]
    if "language" in lowered:
        i = lowered.index("language")
        if i + 1 < len(parts):
            return canonical_lang(parts[i + 1])
    if "translated" in lowered:
        i = lowered.index("translated")
        if i + 1 < len(parts):
            return canonical_lang(parts[i + 1])
    return None


def analyze_pack(path: Path, packs_root: Path) -> Dict[str, Any]:
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError("Top-level JSON must be an object")
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    rel_path = normalize_rel_path(path, packs_root)
    category = str(meta.get("category") or Path(path).stem).strip()
    entry_keys = [k for k in data.keys() if isinstance(k, str) and not k.startswith("_")]

    meta_values = []
    for values in extract_meta_text_fields(meta).values():
        meta_values.extend(values)

    entry_values = []
    entry_language_counts: Counter[str] = Counter()
    for key in entry_keys:
        entry = data.get(key)
        if not isinstance(entry, dict):
            continue
        entry_values.append(key)
        for values in extract_entry_text_fields(entry).values():
            entry_values.extend(values)
        lang, conf, _scores = detect_language_for_values([key] + [v for vals in extract_entry_text_fields(entry).values() for v in vals])
        if lang != "und":
            entry_language_counts[lang] += 1

    all_values = meta_values + entry_values
    detected_lang, confidence, score_map = detect_language_for_values(all_values)
    path_lang = infer_source_language_from_path(rel_path)
    meta_lang = canonical_lang(meta.get("source_language") or meta.get("pack_language") or "")
    source_language = meta_lang if meta_lang != "und" else (path_lang or detected_lang or "und")

    supported = []
    for field in ("supported_languages", "detected_languages"):
        supported.extend(as_list_str(meta.get(field)))
    supported.extend([source_language, detected_lang])
    supported.extend(entry_language_counts.keys())
    supported = [canonical_lang(x) for x in supported if canonical_lang(x) != "und"]
    supported = dedupe_preserve_order(supported)

    detected_languages = dedupe_preserve_order([detected_lang] + list(entry_language_counts.keys()))
    detected_languages = [x for x in detected_languages if x != "und"]

    return {
        "pack_path": rel_path,
        "category": category,
        "cat_id": meta.get("cat_id"),
        "title": meta.get("title"),
        "source_language": source_language,
        "detected_language": detected_lang,
        "detected_languages": detected_languages,
        "language_confidence": score_map or ({detected_lang: confidence} if detected_lang != "und" else {}),
        "supported_languages": supported,
        "entry_language_counts": dict(entry_language_counts),
        "key_count": len(entry_keys),
    }


def build_language_index(
    packs_root: Path,
    *,
    out_json: Path | None = None,
    cache_db: Path | None = None,
    write_meta: bool = False,
    include_undetected: bool = True,
) -> Dict[str, Any]:
    packs_root = Path(packs_root).resolve()
    files = iter_pack_files(packs_root)
    rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    cache = TranslationCache(cache_db) if cache_db else None

    for path in files:
        try:
            row = analyze_pack(path, packs_root)
            if row["source_language"] == "und" and not include_undetected:
                continue
            rows.append(row)
            if cache:
                cache.set_pack_language_meta(
                    pack_path=row["pack_path"],
                    category=row["category"],
                    source_language=row["source_language"],
                    detected_languages=row["detected_languages"],
                    language_confidence=row["language_confidence"],
                    supported_languages=row["supported_languages"],
                    key_count=row["key_count"],
                )
            if write_meta:
                data = read_json(path)
                meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
                meta["source_language"] = row["source_language"]
                meta["detected_languages"] = row["detected_languages"]
                meta["supported_languages"] = row["supported_languages"]
                meta["language_confidence"] = row["language_confidence"]
                data["_meta"] = meta
                write_json(path, data)
        except Exception as e:
            errors.append({"path": normalize_rel_path(path, packs_root), "error": repr(e)})

    by_language = Counter(row["source_language"] for row in rows)
    payload = {
        "_meta": {
            "version": 1,
            "kind": "pack_language_index",
            "packs_root": str(packs_root),
            "total_files": len(files),
            "indexed_files": len(rows),
            "errors": len(errors),
        },
        "summary": {
            "by_source_language": dict(sorted(by_language.items())),
            "total_keys": sum(int(row.get("key_count") or 0) for row in rows),
        },
        "packs": sorted(rows, key=lambda r: (r.get("category") or "", r.get("pack_path") or "")),
        "errors": errors,
    }
    if out_json:
        write_json(out_json, payload)
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a lightweight language index for Semantic Prompt packs.")
    ap.add_argument("--packs-root", required=True, type=Path)
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--cache-db", type=Path, default=None)
    ap.add_argument("--write-meta", action="store_true", help="Write language metadata back into each pack _meta block.")
    ap.add_argument("--skip-undetected", action="store_true")
    args = ap.parse_args()

    payload = build_language_index(
        args.packs_root,
        out_json=args.out_json,
        cache_db=args.cache_db,
        write_meta=bool(args.write_meta),
        include_undetected=not bool(args.skip_undetected),
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
