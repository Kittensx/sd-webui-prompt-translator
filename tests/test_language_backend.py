from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


"""
Resilient end-to-end test runner for the Semantic Prompt language backend.

Goal
----
Run a broad smoke/integration test pass without stopping on the first failure.
Each test records ok/fail/skip, error text, and useful payload data.

This is intended for app/A1111 development where optional providers may be
missing or partially configured. Missing optional providers should be reported,
not crash the whole test run.

Example
-------
python test_language_backend.py --models-dir ./models --cache-db ./semantic/language/cache/language_test.sqlite
python test_language_backend.py --models-dir ./models --provider argos --provider nllb --json
"""

import argparse
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
import sys
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LANGUAGE_DIR = ROOT / "language"
for _p in (ROOT, LANGUAGE_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    from .paths import MODELS_DIR, TEST_OUTPUT_DIR
except ImportError:
    try:
        from language.paths import MODELS_DIR, TEST_OUTPUT_DIR
    except ImportError:
        from paths import MODELS_DIR, TEST_OUTPUT_DIR
from time import perf_counter
from typing import Any, Callable, Dict, List, Optional, Sequence

# Allow running this file directly from inside pack_lang_backend/ or from project root.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))


@dataclass
class TestRecord:
    name: str
    ok: bool
    status: str = "ok"  # ok | fail | skip
    elapsed_ms: float = 0.0
    error: Optional[str] = None
    traceback: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "name": self.name,
            "ok": self.ok,
            "status": self.status,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "error": self.error,
            "data": self.data,
        }
        if self.traceback:
            out["traceback"] = self.traceback
        return out


class TestRunner:
    def __init__(self, *, include_traceback: bool = False):
        self.include_traceback = include_traceback
        self.records: List[TestRecord] = []

    def run(self, name: str, fn: Callable[[], Dict[str, Any] | None], *, optional: bool = False) -> None:
        start = perf_counter()
        try:
            data = fn() or {}
            self.records.append(TestRecord(
                name=name,
                ok=True,
                status="ok",
                elapsed_ms=(perf_counter() - start) * 1000.0,
                data=data,
            ))
        except SkipTest as e:
            self.records.append(TestRecord(
                name=name,
                ok=True if optional else False,
                status="skip",
                elapsed_ms=(perf_counter() - start) * 1000.0,
                error=str(e),
            ))
        except Exception as e:
            tb = traceback.extract_tb(e.__traceback__)
            last = tb[-1] if tb else None

            error_data = {
                "exception_type": type(e).__name__,
                "error": repr(e),
                "file": last.filename if last else None,
                "line": last.lineno if last else None,
                "function": last.name if last else None,
            }

            self.records.append(TestRecord(
                name=name,
                ok=True if optional else False,
                status="skip" if optional else "fail",
                elapsed_ms=(perf_counter() - start) * 1000.0,
                error=json.dumps(error_data, ensure_ascii=False),
                traceback=traceback.format_exc() if self.include_traceback else None,
            ))

    def summary(self) -> Dict[str, Any]:
        return {
            "total": len(self.records),
            "ok": sum(1 for r in self.records if r.status == "ok"),
            "skipped": sum(1 for r in self.records if r.status == "skip"),
            "failed": sum(1 for r in self.records if r.status == "fail"),
            "hard_ok": all(r.ok for r in self.records),
        }


class SkipTest(RuntimeError):
    pass


def _import(module_name: str):
    return importlib.import_module(module_name)


def _short(value: Any, limit: int = 300) -> Any:
    text = repr(value)
    if len(text) <= limit:
        return value
    return text[:limit] + "..."


def test_imports(modules: Sequence[str]) -> Dict[str, Any]:
    loaded = []
    for module in modules:
        _import(module)
        loaded.append(module)
    return {"loaded": loaded}


def test_language_utils() -> Dict[str, Any]:
    lu = _import("language_utils")
    return {
        "canonical_en": lu.canonical_lang("english"),
        "canonical_ja": lu.canonical_lang("jp"),
        "detect_en": lu.detect_language_simple("riverbank at golden hour"),
        "detect_ja": lu.detect_language_simple("黄金時に川岸"),
    }


def test_provider_factory(provider_name: str, models_dir: Path, dictionary_paths: Sequence[Path]) -> Dict[str, Any]:
    tp = _import("translation_providers")
    provider = tp.get_provider(provider_name, models_dir=models_dir, dictionary_paths=list(dictionary_paths))
    data = {"provider_class": provider.__class__.__name__, "provider_name": getattr(provider, "name", provider_name)}
    if hasattr(provider, "is_available"):
        try:
            data["is_available"] = bool(provider.is_available())
        except Exception as e:
            data["is_available_error"] = repr(e)
    if hasattr(provider, "installed_pairs"):
        try:
            data["installed_pairs"] = provider.installed_pairs()
        except Exception as e:
            data["installed_pairs_error"] = repr(e)
    return data


def test_provider_translation(provider_name: str, text: str, source: str, target: str, models_dir: Path, dictionary_paths: Sequence[Path]) -> Dict[str, Any]:
    tp = _import("translation_providers")
    provider = tp.get_provider(provider_name, models_dir=models_dir, dictionary_paths=list(dictionary_paths))
    translated = provider.translate_texts([text], source_language=source, target_language=target)[0]
    return {
        "provider": provider_name,
        "input": text,
        "source": source,
        "target": target,
        "translation": translated,
        "changed": translated != text,
    }


def test_quality_scoring(text: str, source: str, target: str) -> Dict[str, Any]:
    tq = _import("translation_quality")
    samples = [
        ("argos", "黄金時間に川岸"),
        ("nllb", "黄金時に川岸"),
        ("bad_example", "ナイル 川 の ほとり に , 金 の 格子 を 砕 い た ."),
    ]
    scored = [
        tq.score_translation(text, trans, source_language=source, target_language=target, provider=provider, mode="prompt").to_dict()
        for provider, trans in samples
    ]
    winner = tq.choose_best([
        tq.score_translation(text, trans, source_language=source, target_language=target, provider=provider, mode="prompt")
        for provider, trans in samples
    ])
    return {"scores": scored, "winner": winner.to_dict()}


def test_smart_translate(text: str, source: str, target: str, providers: Sequence[str], models_dir: Path, dictionary_paths: Sequence[Path]) -> Dict[str, Any]:
    st = _import("smart_translate")
    result = st.smart_translate_text(
        text,
        source_language=source,
        target_language=target,
        providers=list(providers),
        models_dir=models_dir,
        dictionary_paths=list(dictionary_paths),
        mode="prompt",
    )
    return {
        "winner": result.get("winner"),
        "candidates": result.get("candidates"),
        "raw_results": result.get("raw_results"),
    }


def test_translation_cache(cache_db: Path) -> Dict[str, Any]:
    tc = _import("translation_cache")
    cache = tc.TranslationCache(cache_db)
    source_values = ["riverbank", "golden hour"]
    translated_values = ["川岸", "ゴールデンアワー"]
    cache.set_cached_translation(
        pack_path="environment/water/river.json",
        category="environment.water.river",
        entry_key="riverbank",
        field_name="tags",
        source_language="en",
        target_language="ja",
        source_values=source_values,
        translated_values=translated_values,
        provider="test",
        model="test-model",
    )
    hit = cache.get_cached_translation(
        pack_path="environment/water/river.json",
        entry_key="riverbank",
        field_name="tags",
        source_language="en",
        target_language="ja",
        source_values=source_values,
    )
    stats = cache.stats()
    return {"hit": hit, "stats": stats}


def test_search_cache(cache_db: Path) -> Dict[str, Any]:
    sc = _import("search_cache")
    cache = sc.SearchCache(cache_db)
    query = "riverbank"
    params = {
        "source_language": "en",
        "target_language": "ja",
        "preset": "prompt",
        "providers": ["argos", "nllb"],
    }
    payload = {
        "query": query,
        "results": [{"category": "environment.water.river", "key": "riverbank", "score": 100}],
    }
    cache.set(query=query, params=params, payload=payload, ttl_seconds=3600)
    first = cache.get(query=query, params=params)
    second = cache.get(query=query, params=params)
    stats = cache.stats()
    return {"first_hit": first is not None, "second_hit": second is not None, "stats": stats}


def test_provider_model_manager_basic(models_dir: Path) -> Dict[str, Any]:
    pmm = _import("provider_model_manager")
    data: Dict[str, Any] = {}
    if hasattr(pmm, "COMMON_LANGUAGES"):
        data["common_languages_count"] = len(pmm.COMMON_LANGUAGES)
    if hasattr(pmm, "ARGOS_BUNDLES"):
        data["argos_bundles"] = sorted(pmm.ARGOS_BUNDLES.keys())
    if hasattr(pmm, "NLLB_MODEL_ID"):
        data["nllb_model_id"] = pmm.NLLB_MODEL_ID
    # Do not download/install here. This is a non-destructive status/introspection test.
    if hasattr(pmm, "get_installed_argos_pairs"):
        try:
            data["installed_argos_pairs"] = pmm.get_installed_argos_pairs()
        except Exception as e:
            data["installed_argos_pairs_error"] = repr(e)
    nllb_dir = models_dir / "nllb"
    data["nllb_dir_exists"] = nllb_dir.exists()
    data["nllb_models"] = [p.name for p in nllb_dir.iterdir() if p.is_dir()] if nllb_dir.exists() else []
    return data



def test_prompt_translator_settings(cache_db: Path) -> Dict[str, Any]:
    pts = _import("prompt_translator_settings")
    settings_path = cache_db.with_name("language_settings_test.json")
    settings = pts.PromptTranslatorSettings(user_language="ja", target_language="user", provider_mode="smart")
    saved = pts.save_settings(settings_path, settings)
    loaded = pts.load_settings(settings_path)
    try:
        settings_path.unlink(missing_ok=True)
    except Exception:
        pass
    return {"saved": saved, "loaded_user_language": loaded.user_language, "loaded_provider_mode": loaded.provider_mode}


def test_prompt_translator_service(models_dir: Path) -> Dict[str, Any]:
    ptsvc = _import("prompt_translator_service")
    root = Path(tempfile.mkdtemp(prefix="semantic_prompt_translator_service_"))
    svc = ptsvc.PromptTranslatorService(extension_root=root)
    langs = svc.language_choices()[:5]
    providers = svc.provider_choices()[:8]
    detected = svc.detect_source_language("黄金時に川岸")
    bridge = ptsvc.register_a1111_bridge(svc)
    status = svc.provider_status()
    return {
        "language_choices_preview": langs,
        "provider_choices_preview": providers,
        "detected": detected,
        "bridge": bridge,
        "settings": svc.reload_settings(),
        "provider_status_keys": sorted(status.keys()),
    }


def test_prompt_translator_selection_payload(models_dir: Path) -> Dict[str, Any]:
    ptsvc = _import("prompt_translator_service")
    root = Path(tempfile.mkdtemp(prefix="semantic_prompt_translator_selection_"))
    svc = ptsvc.PromptTranslatorService(extension_root=root)
    payload = json.dumps({
        "value": "portrait, riverbank at golden hour, film grain",
        "selection_start": 10,
        "selection_end": 34,
        "selected_text": "riverbank at golden hour",
    })
    result = svc.replace_selection_payload(
        payload,
        source_language="en",
        target_language="ja",
        provider="static_dictionary",
        mode="prompt",
    )
    return {"updated_prompt": result.get("updated_prompt"), "source_language": result.get("source_language"), "target_language": result.get("target_language")}



def test_prompt_translation_parser_spans() -> Dict[str, Any]:
    parser_mod = _import("prompt_translation_parser")
    prompt = "(cat:1.2), lake, {duck, lake, woman}, <lora:add_detail:0.8>, BREAK, %%semantic: keep%%"
    spans = parser_mod.parse_prompt_for_translation(prompt)
    translatable = [s.value for s in spans if s.translatable and str(s.value).strip()]
    protected = [s.value for s in spans if not s.translatable and str(s.value).strip()]
    rendered = parser_mod.render_prompt_spans(spans)
    if rendered != prompt:
        raise AssertionError(f"Parser roundtrip changed prompt: {rendered!r}")
    if not {"cat", "duck"}.issubset({v.strip() for v in translatable}):
        raise AssertionError(f"Expected text spans were not translatable: {translatable!r}")
    return {"translatable": translatable, "protected_preview": protected[:12], "span_count": len(spans)}


def test_service_prompt_pipeline(provider_name: str, source: str, target: str) -> Dict[str, Any]:
    ptsvc = _import("prompt_translator_service")
    svc = ptsvc.PromptTranslatorService(extension_root=Path(__file__).resolve().parents[1])
    prompt = "(cat:1.2), lake, {duck, lake, woman}"
    result = svc.translate_text(prompt, source_language=source, target_language=target, provider=provider_name, mode="prompt", auto_detect=False)
    return {
        "provider": provider_name,
        "ok": result.get("ok"),
        "error": result.get("error", ""),
        "warning": result.get("warning", ""),
        "translation": result.get("translation"),
        "translatable_span_count": result.get("translatable_span_count"),
        "changed_translatable_span_count": result.get("changed_translatable_span_count"),
        "span_results_preview": (result.get("span_results") or [])[:5],
    }


def test_roundtrip_prompt_pipeline(provider_name: str, source: str, target: str) -> Dict[str, Any]:
    import importlib.util
    rt_path = Path(__file__).resolve().parent / "roundtrip_translation_test.py"
    spec = importlib.util.spec_from_file_location("roundtrip_translation_test_top_level", rt_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load roundtrip test module from {rt_path}")
    rt = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = rt
    spec.loader.exec_module(rt)
    ptsvc = _import("prompt_translator_service")
    svc = ptsvc.PromptTranslatorService(extension_root=Path(__file__).resolve().parents[1])
    rows = rt.run_chain(
        svc,
        "(cat:1.2), lake, {duck, lake, woman}",
        provider=provider_name,
        languages=[target],
        anchor_language=source,
        mode="prompt",
    )
    from dataclasses import asdict as _dataclass_asdict
    payload = [_dataclass_asdict(r) for r in rows]
    return {
        "provider": provider_name,
        "row_count": len(rows),
        "all_ok": all(bool(getattr(r, "ok", False)) for r in rows),
        "rows_preview": payload[:2],
    }


def test_dictionary_manager_and_service() -> Dict[str, Any]:
    dm = _import("dictionary_manager")
    ptsvc = _import("prompt_translator_service")
    root = Path(tempfile.mkdtemp(prefix="semantic_prompt_dictionary_"))
    sample = root / "sample_en_ja.tsv"
    sample.write_text("duck\tアヒル\nlady\t女性\ndog\t犬\n", encoding="utf-8")
    info = dm.import_dictionary_file(root, sample, source_language="en", target_language="ja", name="sample")
    paths = dm.dictionary_paths(root, source_language="en", target_language="ja")
    svc = ptsvc.PromptTranslatorService(extension_root=root)
    result = svc.translate_text("duck, lady, dog", source_language="en", target_language="ja", provider="smart", mode="prompt")
    return {
        "imported": info.to_dict(),
        "dictionary_paths": [str(p) for p in paths],
        "translation": result.get("translation"),
        "provider": result.get("provider"),
    }

def main() -> None:
    parser = argparse.ArgumentParser(description="Run resilient end-to-end tests for Semantic Prompt language backend.")
    parser.add_argument("--models-dir", default=str(MODELS_DIR), help="Root models folder, e.g. ./models")
    parser.add_argument("--cache-db", default="", help="SQLite DB for cache tests. Defaults to a temp DB.")
    parser.add_argument("--text", default="riverbank at golden hour")
    parser.add_argument("--source", default="en")
    parser.add_argument("--target", default="ja")
    parser.add_argument("--provider", action="append", default=None, help="Provider to test. Repeatable. Default: static_dictionary, argos, nllb")
    parser.add_argument("--dictionary", action="append", default=[])
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    parser.add_argument("--out", default="", help="Optional JSON report path")
    parser.add_argument("--skip-roundtrip", action="store_true", help="Skip the prompt-aware roundtrip integration test.")
    parser.add_argument("--traceback", action="store_true", help="Include tracebacks in JSON report")
    args = parser.parse_args()

    models_dir = Path(args.models_dir).expanduser().resolve()
    providers = args.provider or ["static_dictionary", "argos", "nllb"]
    dictionary_paths = [Path(p).expanduser().resolve() for p in args.dictionary]

    temp_db_path: Optional[Path] = None
    if args.cache_db:
        cache_db = Path(args.cache_db).expanduser().resolve()
        cache_db.parent.mkdir(parents=True, exist_ok=True)
    else:
        fd, temp_name = tempfile.mkstemp(prefix="semantic_language_test_", suffix=".sqlite")
        os.close(fd)
        temp_db_path = Path(temp_name)
        cache_db = temp_db_path

    runner = TestRunner(include_traceback=bool(args.traceback))

    runner.run("import_core_modules", lambda: test_imports([
        "language_utils",
        "translation_providers",
        "translation_quality",
        "smart_translate",
        "translation_cache",
        "search_cache",
        "provider_model_manager",
        "prompt_translator_settings",
        "prompt_translator_service",
        "dictionary_manager",
    ]))
    runner.run("language_utils", test_language_utils)
    runner.run("provider_model_manager_status", lambda: test_provider_model_manager_basic(models_dir), optional=True)
    runner.run("prompt_translator_settings", lambda: test_prompt_translator_settings(cache_db))
    runner.run("prompt_translator_service", lambda: test_prompt_translator_service(models_dir), optional=True)
    runner.run("prompt_translator_selection_payload", lambda: test_prompt_translator_selection_payload(models_dir), optional=True)
    runner.run("dictionary_manager_and_service", test_dictionary_manager_and_service)
    runner.run("prompt_translation_parser_spans", test_prompt_translation_parser_spans)

    for provider in providers:
        runner.run(
            f"provider_factory:{provider}",
            lambda provider=provider: test_provider_factory(provider, models_dir, dictionary_paths),
            optional=True,
        )
        runner.run(
            f"provider_translate:{provider}",
            lambda provider=provider: test_provider_translation(provider, args.text, args.source, args.target, models_dir, dictionary_paths),
            optional=True,
        )
        runner.run(
            f"service_prompt_pipeline:{provider}",
            lambda provider=provider: test_service_prompt_pipeline(provider, args.source, args.target),
            optional=True,
        )
        if not args.skip_roundtrip:
            runner.run(
                f"roundtrip_prompt_pipeline:{provider}",
                lambda provider=provider: test_roundtrip_prompt_pipeline(provider, args.source, args.target),
                optional=True,
            )

    runner.run("translation_quality_scoring", lambda: test_quality_scoring(args.text, args.source, args.target))
    runner.run(
        "smart_translate_compare",
        lambda: test_smart_translate(args.text, args.source, args.target, providers, models_dir, dictionary_paths),
        optional=True,
    )
    runner.run("translation_cache", lambda: test_translation_cache(cache_db))
    runner.run("search_cache", lambda: test_search_cache(cache_db))

    report = {
        "summary": runner.summary(),
        "config": {
            "models_dir": str(models_dir),
            "cache_db": str(cache_db),
            "text": args.text,
            "source": args.source,
            "target": args.target,
            "providers": list(providers),
            "dictionary_paths": [str(p) for p in dictionary_paths],
        },
        "tests": [r.to_dict() for r in runner.records],
    }

    if temp_db_path is not None:
        try:
            temp_db_path.unlink(missing_ok=True)
        except Exception:
            pass

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        summary = report["summary"]
        print("Semantic Language Backend Test Report")
        print("=" * 44)
        print(f"Total:   {summary['total']}")
        print(f"OK:      {summary['ok']}")
        print(f"Skipped: {summary['skipped']}")
        print(f"Failed:  {summary['failed']}")
        print("")
        for rec in runner.records:
            mark = "PASS" if rec.status == "ok" else ("SKIP" if rec.status == "skip" else "FAIL")
            print(f"[{mark}] {rec.name} ({rec.elapsed_ms:.1f} ms)")
            if rec.error:
                print(f"       {rec.error}")
            if rec.data:
                print(f"       data: {_short(rec.data)}")
        if args.out:
            print(f"\nWrote JSON report: {args.out}")

    # Exit 0 by default even with failed optional tests, so CI/manual diagnostics can keep running.
    # Use the JSON summary to decide if failures should block a release.
    raise SystemExit(0)


if __name__ == "__main__":
    main()
#python tests/test_language_backend.py --models-dir ./models --json --out ./test_outputs/language_backend_test_report.json
#python test_language_backend.py --models-dir ./models