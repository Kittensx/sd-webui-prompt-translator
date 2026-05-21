from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from language.utils.language_utils import canonical_lang, detect_language
from language.translation.translation_cache import TranslationCache
from language.translation.translation_providers import get_provider
from language.translation.search_cache import SearchResultCache, SearchCachePolicy


def import_pack_search_engine(path: Path):
    spec = importlib.util.spec_from_file_location("pack_search_engine", str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not import pack_search_engine from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["pack_search_engine"] = module
    spec.loader.exec_module(module)
    return module


def multilingual_search(
    *,
    query: str,
    packs_root: Path,
    pack_search_engine_path: Path,
    cache_db: Path,
    provider_name: str = "noop",
    canonical_language: str = "en",
    max_results: int = 25,
    preset: str = "broad",
    display_format: str = "equals",
    search_cache_db: Path | None = None,
    use_search_cache: bool = True,
    search_cache_ttl_days: float | None = 30,
    search_cache_max_rows: int | None = 5000,
    search_cache_max_bytes: int | None = 50 * 1024 * 1024,
    catalog_fingerprint: str | None = None,
) -> Dict[str, Any]:
    detected, confidence, scores = detect_language(query)
    canonical = canonical_lang(canonical_language)
    provider = get_provider(provider_name)
    provider_id = getattr(provider, "name", provider_name or "unknown")
    cache = TranslationCache(cache_db)

    search_context = {
        "packs_root": str(Path(packs_root).resolve()),
        "pack_search_engine_path": str(Path(pack_search_engine_path).resolve()),
        "canonical_language": canonical,
        "max_results": int(max_results),
        "preset": preset,
        "display_format": display_format,
        "catalog_fingerprint": catalog_fingerprint or "manual",
    }
    search_cache = None
    if search_cache_db and use_search_cache:
        search_cache = SearchResultCache(
            search_cache_db,
            policy=SearchCachePolicy(
                enabled=True,
                ttl_days=search_cache_ttl_days,
                max_rows=search_cache_max_rows,
                max_bytes=search_cache_max_bytes,
            ),
        )
        cached = search_cache.get(
            query=query,
            query_language=detected,
            canonical_language=canonical,
            provider=provider_id,
            search_context=search_context,
            record_history=False,
        )
        if cached.hit and cached.payload is not None:
            return cached.payload

    queries = [query]
    candidate_source_languages = []
    if detected != "und" and detected != canonical:
        candidate_source_languages.append(detected)
    # Some scripts are ambiguous. A kanji-only query may be scored as zh even
    # when the user's pack vocabulary is Japanese, so try any high-scoring
    # non-canonical candidate too.
    for lang, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        lang = canonical_lang(lang)
        if lang != "und" and lang != canonical and score >= 0.40 and lang not in candidate_source_languages:
            candidate_source_languages.append(lang)

    for src_lang in candidate_source_languages:
        queries.extend(cache.get_or_create_query_translation(
            query,
            source_language=src_lang,
            target_language=canonical,
            provider_obj=provider,
        ))
    # preserve order, dedupe
    queries = list(dict.fromkeys(q for q in queries if q and q.strip()))

    engine = import_pack_search_engine(pack_search_engine_path)
    index = engine.build_index(Path(packs_root))
    merged: Dict[tuple[str, str], Any] = {}
    query_results: Dict[str, int] = {}

    for q in queries:
        options = engine.SearchOptions(
            packs_root=Path(packs_root),
            display_format=display_format,
            max_results=max_results,
            preset=preset,
            advanced=False,
            show_warnings=False,
        )
        directives = engine.AdvancedDirectives()
        results, warnings = engine.search_index(index, q, options, directives)
        query_results[q] = len(results)
        for r in results:
            key = (r.category, r.key)
            if key not in merged or r.score > merged[key].score:
                merged[key] = r

    ranked = sorted(merged.values(), key=lambda r: (-r.score, r.category, r.key))[:max_results]
    payload = {
        "query": query,
        "detected_language": detected,
        "language_confidence": confidence,
        "language_scores": scores,
        "canonical_language": canonical,
        "expanded_queries": queries,
        "query_result_counts": query_results,
        "results": [engine.result_to_json_obj(r) for r in ranked],
        "search_cache": {"hit": False, "cache_key": None},
    }
    if search_cache is not None:
        cache_key = search_cache.set(
            query=query,
            query_language=detected,
            canonical_language=canonical,
            provider=provider_id,
            search_context=search_context,
            payload=payload,
            ttl_days=search_cache_ttl_days,
        )
        payload["search_cache"] = {"hit": False, "cache_key": cache_key}
        search_cache.record_history(
            query=query,
            query_language=detected,
            canonical_language=canonical,
            provider=provider_id,
            cache_key=cache_key,
            cache_hit=False,
            result_count=len(payload.get("results") or []),
            expanded_queries=payload.get("expanded_queries") or [],
            search_context=search_context,
        )
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description="Search packs using a translated query fallback.")
    ap.add_argument("query")
    ap.add_argument("--packs-root", required=True, type=Path)
    ap.add_argument("--pack-search-engine", required=True, type=Path)
    ap.add_argument("--cache-db", required=True, type=Path)
    ap.add_argument("--provider", default="noop")
    ap.add_argument("--canonical-language", default="en")
    ap.add_argument("--max-results", type=int, default=25)
    ap.add_argument("--preset", default="broad")
    ap.add_argument("--format", default="equals", choices=["equals", "colon"])
    ap.add_argument("--search-cache-db", type=Path, default=None, help="Optional SQLite DB for caching final user search results")
    ap.add_argument("--no-search-cache", action="store_true", help="Disable user search result cache even when --search-cache-db is provided")
    ap.add_argument("--search-cache-ttl-days", type=float, default=30)
    ap.add_argument("--search-cache-max-rows", type=int, default=5000)
    ap.add_argument("--search-cache-max-bytes", type=int, default=50 * 1024 * 1024)
    ap.add_argument("--catalog-fingerprint", default=None, help="Optional version/hash of current pack catalogue to avoid stale cached searches")
    args = ap.parse_args()

    payload = multilingual_search(
        query=args.query,
        packs_root=args.packs_root,
        pack_search_engine_path=args.pack_search_engine,
        cache_db=args.cache_db,
        provider_name=args.provider,
        canonical_language=args.canonical_language,
        max_results=args.max_results,
        preset=args.preset,
        display_format=args.format,
        search_cache_db=args.search_cache_db,
        use_search_cache=not args.no_search_cache,
        search_cache_ttl_days=args.search_cache_ttl_days,
        search_cache_max_rows=args.search_cache_max_rows,
        search_cache_max_bytes=args.search_cache_max_bytes,
        catalog_fingerprint=args.catalog_fingerprint,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
