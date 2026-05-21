from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import argparse
import csv
import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LANGUAGE_DIR = ROOT / "language"
for _path in (ROOT, LANGUAGE_DIR, HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

try:
    from .constants import DEFAULT_ANCHOR_LANGUAGE, DEFAULT_ROUNDTRIP_CHAIN, DEFAULT_SMOKE_TEXT
    from .paths import TEST_OUTPUT_DIR
except ImportError:
    try:
        from language.constants import DEFAULT_ANCHOR_LANGUAGE, DEFAULT_ROUNDTRIP_CHAIN, DEFAULT_SMOKE_TEXT
        from language.paths import TEST_OUTPUT_DIR
    except ImportError:
        from constants import DEFAULT_ANCHOR_LANGUAGE, DEFAULT_ROUNDTRIP_CHAIN, DEFAULT_SMOKE_TEXT
        from paths import TEST_OUTPUT_DIR
from typing import Any, Dict, Iterable, List, Sequence

from language.parser.prompt_translation_parser import parse_prompt_for_translation
from language.translation.prompt_translator_service import PromptTranslatorService


DEFAULT_PROMPTS = [
    "(cat:1.2), lake, {duck, lake, woman}",
    "<lora:add_detail:0.8>, BREAK, cinematic lighting, [bad hands:0.5]",
    "[cat:dog:0.35], forest | lake | city, AND woman holding flowers",
    "%%semantic: keep subject consistent%%, a red fox, regex /cat|dog|bird/",
]


@dataclass
class StageResult:
    provider: str
    stage_index: int
    source_language: str
    target_language: str
    input_text: str
    translated_text: str
    back_to_anchor_text: str
    similarity_to_anchor: float
    changed_ratio: float
    protected_spans_preserved: bool
    ok: bool
    error: str = ""
    warning: str = ""
    translatable_span_count: int = 0
    changed_translatable_span_count: int = 0
    no_translatable_span_changed: bool = False
    prompt_spans: List[Dict[str, Any]] | None = None
    span_results: List[Dict[str, Any]] | None = None


def normalize_prompt(text: str) -> str:
    text = str(text or "").strip().casefold()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    return text


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_prompt(a), normalize_prompt(b)).ratio()


def changed_ratio(a: str, b: str) -> float:
    return 1.0 - similarity(a, b)


def protected_values(text: str) -> List[str]:
    return [span.value for span in parse_prompt_for_translation(text) if not span.translatable and span.value.strip()]


def protected_spans_preserved(before: str, after: str) -> bool:
    before_values = protected_values(before)
    after_values = protected_values(after)
    return all(value in after_values or value in after for value in before_values)


def translate(service: PromptTranslatorService, text: str, *, provider: str, source: str, target: str, mode: str) -> Dict[str, Any]:
    return service.translate_text(
        text,
        source_language=source,
        target_language=target,
        provider=provider,
        mode=mode,
        auto_detect=False,
    )


def package_available(package_name: str) -> bool:
    return importlib.util.find_spec(package_name) is not None


def run_pip_install(package_name: str, *, quiet: bool = False) -> bool:
    cmd = [sys.executable, "-m", "pip", "install", package_name]
    if not quiet:
        print(f"Installing Python package: {package_name}")
    completed = subprocess.run(cmd, check=False)
    return completed.returncode == 0


def direct_stage_pairs(anchor_language: str, languages: Sequence[str]) -> List[tuple[str, str]]:
    """
    Return logical stage pairs requested by the roundtrip test.
    Provider implementations may satisfy these with direct models or routed models.
    """
    pairs: list[tuple[str, str]] = []
    if not languages:
        return pairs

    current = anchor_language
    for next_lang in languages:
        pairs.append((current, next_lang))
        pairs.append((next_lang, anchor_language))
        current = next_lang

    reverse_langs = [anchor_language] + list(languages[:-1])
    current = languages[-1]
    for next_lang in reversed(reverse_langs):
        pairs.append((current, next_lang))
        current = next_lang

    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pair in pairs:
        if pair[0] != pair[1] and pair not in seen:
            seen.add(pair)
            deduped.append(pair)
    return deduped


# Backwards-compatible name used by older docs/scripts.
def required_language_pairs(anchor_language: str, languages: Sequence[str]) -> List[tuple[str, str]]:
    return direct_stage_pairs(anchor_language, languages)


def argos_pair_installed(source: str, target: str) -> bool:
    try:
        try:
            from language.provider_model_manager import get_installed_argos_pairs
        except Exception:
            from language.providers.provider_model_manager import get_installed_argos_pairs
        return (source, target) in set(get_installed_argos_pairs())
    except Exception:
        return False


def installed_argos_pairs() -> set[tuple[str, str]]:
    try:
        try:
            from language.provider_model_manager import get_installed_argos_pairs
        except Exception:
            from language.providers.provider_model_manager import get_installed_argos_pairs
        return set(get_installed_argos_pairs())
    except Exception:
        return set()


def find_argos_route(source: str, target: str, installed: set[tuple[str, str]], *, bridge: str = "en", max_hops: int = 3) -> list[tuple[str, str]]:
    if source == target:
        return []
    if (source, target) in installed:
        return [(source, target)]
    if bridge not in {source, target} and (source, bridge) in installed and (bridge, target) in installed:
        return [(source, bridge), (bridge, target)]

    graph: dict[str, set[str]] = {}
    for src, tgt in installed:
        graph.setdefault(src, set()).add(tgt)

    queue: list[tuple[str, list[tuple[str, str]]]] = [(source, [])]
    seen = {source}
    while queue:
        current, path = queue.pop(0)
        if len(path) >= max_hops:
            continue
        for nxt in sorted(graph.get(current, set())):
            if nxt in seen:
                continue
            new_path = path + [(current, nxt)]
            if nxt == target:
                return new_path
            seen.add(nxt)
            queue.append((nxt, new_path))
    return []


def required_argos_model_pairs(anchor_language: str, languages: Sequence[str], *, bridge: str = "en") -> list[tuple[str, str]]:
    """
    Return the model pairs that should be installed for this test. Prefer direct
    installed pairs; otherwise use an English bridge route. This avoids requiring
    rare direct packages like ja->fr when ja->en and en->fr are enough.
    """
    installed = installed_argos_pairs()
    needed: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for src, tgt in direct_stage_pairs(anchor_language, languages):
        route = find_argos_route(src, tgt, installed, bridge=bridge)
        if route:
            for pair in route:
                if pair not in seen:
                    seen.add(pair)
                    needed.append(pair)
            continue
        candidate_route = [(src, bridge), (bridge, tgt)] if bridge not in {src, tgt} else [(src, tgt)]
        for pair in candidate_route:
            if pair[0] != pair[1] and pair not in seen:
                seen.add(pair)
                needed.append(pair)
    return needed


def install_argos_pair(source: str, target: str, *, quiet: bool = False) -> tuple[bool, str]:
    try:
        try:
            from language.provider_model_manager import install_argos_language_pair
        except Exception:
            from language.providers.provider_model_manager import install_argos_language_pair
    except ModuleNotFoundError:
        return False, "provider_model_manager is not importable"

    try:
        changed = install_argos_language_pair(source, target, update_index=True)
        return True, "installed" if changed else "already installed"
    except Exception as exc:
        return False, repr(exc)


def preflight_argos(
    *,
    anchor_language: str,
    languages: Sequence[str],
    auto_install_python_deps: bool,
    auto_install_models: bool,
    quiet: bool,
) -> tuple[bool, list[str]]:
    """
    Validate and optionally install Argos dependencies/model pairs needed for this roundtrip.
    Missing direct pairs can be satisfied by installed bridge routes, usually via English.
    """
    messages: list[str] = []

    if not package_available("argostranslate"):
        if auto_install_python_deps:
            if not run_pip_install("argostranslate", quiet=quiet):
                return False, ["Failed to install Python package: argostranslate"]
        else:
            return False, [
                "Missing Python package: argostranslate. Re-run with --auto-install-python-deps or install it manually."
            ]

    needed_pairs = required_argos_model_pairs(anchor_language, languages, bridge=anchor_language)
    installed = installed_argos_pairs()
    missing_pairs = [pair for pair in needed_pairs if pair not in installed]

    route_notes = []
    installed_after = set(installed)
    for src, tgt in direct_stage_pairs(anchor_language, languages):
        route = find_argos_route(src, tgt, installed_after, bridge=anchor_language)
        if route:
            route_notes.append(f"{src}->{tgt} via " + " -> ".join([route[0][0], *[b for _, b in route]]))

    if not missing_pairs:
        messages.append("All required Argos route pairs are installed.")
        messages.extend(f"Route: {note}" for note in route_notes[:12])
        return True, messages

    if not auto_install_models:
        pair_text = ", ".join(f"{source}->{target}" for source, target in missing_pairs)
        return False, [
            f"Missing Argos route pairs: {pair_text}. "
            "Re-run with --auto-install-models to download/install available Argos packages."
        ]

    still_missing: list[str] = []
    for source, target in missing_pairs:
        ok, detail = install_argos_pair(source, target, quiet=quiet)
        if ok and argos_pair_installed(source, target):
            messages.append(f"Installed Argos language pair: {source}->{target}")
        else:
            still_missing.append(f"{source}->{target} ({detail or 'install did not register'})")

    if still_missing:
        return False, ["Could not install required Argos route pairs: " + ", ".join(still_missing), *messages]

    messages.append("All required Argos route pairs are installed.")
    return True, messages


def run_chain(
    service: PromptTranslatorService,
    prompt: str,
    *,
    provider: str,
    languages: Sequence[str],
    anchor_language: str = "en",
    mode: str = "prompt",
) -> List[StageResult]:
    """
    Forward chain: anchor -> B -> C -> D.
    At every forward stage, translate the result back to anchor_language so drift can be measured early.
    Final stage also returns D -> C -> B -> anchor as an end-to-end roundtrip check.
    """
    if not languages:
        return []

    current = prompt
    current_lang = anchor_language
    rows: List[StageResult] = []

    for i, next_lang in enumerate(languages, start=1):
        error = ""
        ok = True
        translated = current
        back = current
        try:
            forward = translate(service, current, provider=provider, source=current_lang, target=next_lang, mode=mode)
            translated = str(forward.get("translation") or current)
            ok = bool(forward.get("ok", True))
            if not ok:
                error = str(forward.get("error") or "forward translation failed")

            warning = str(forward.get("warning") or "")
            no_span_changed = bool(forward.get("no_translatable_span_changed", False))

            backward = translate(service, translated, provider=provider, source=next_lang, target=anchor_language, mode=mode)
            back = str(backward.get("translation") or translated)
            if not backward.get("ok", True):
                ok = False
                error = (error + "; " if error else "") + str(backward.get("error") or "anchor back-translation failed")
            if backward.get("warning"):
                warning = (warning + "; " if warning else "") + str(backward.get("warning"))
        except Exception as exc:
            ok = False
            error = repr(exc)
            warning = ""
            no_span_changed = False
            forward = {}

        rows.append(StageResult(
            provider=provider,
            stage_index=i,
            source_language=current_lang,
            target_language=next_lang,
            input_text=current,
            translated_text=translated,
            back_to_anchor_text=back,
            similarity_to_anchor=similarity(prompt, back),
            changed_ratio=changed_ratio(prompt, back),
            protected_spans_preserved=protected_spans_preserved(current, translated),
            ok=ok,
            error=error,
            warning=warning,
            translatable_span_count=int(forward.get("translatable_span_count") or 0),
            changed_translatable_span_count=int(forward.get("changed_translatable_span_count") or 0),
            no_translatable_span_changed=no_span_changed,
            prompt_spans=forward.get("prompt_spans"),
            span_results=forward.get("span_results"),
        ))
        current = translated
        current_lang = next_lang

    # Full reverse chain, recorded as one extra diagnostic row.
    reverse_current = current
    reverse_lang = current_lang
    error = ""
    ok = True
    for next_lang in reversed([anchor_language] + list(languages[:-1])):
        try:
            reverse = translate(service, reverse_current, provider=provider, source=reverse_lang, target=next_lang, mode=mode)
            reverse_current = str(reverse.get("translation") or reverse_current)
            if not reverse.get("ok", True):
                ok = False
                error = (error + "; " if error else "") + str(reverse.get("error") or f"reverse {reverse_lang}->{next_lang} failed")
        except Exception as exc:
            ok = False
            error = (error + "; " if error else "") + repr(exc)
        reverse_lang = next_lang

    rows.append(StageResult(
        provider=provider,
        stage_index=len(languages) + 1,
        source_language="reverse_chain",
        target_language=anchor_language,
        input_text=current,
        translated_text=reverse_current,
        back_to_anchor_text=reverse_current,
        similarity_to_anchor=similarity(prompt, reverse_current),
        changed_ratio=changed_ratio(prompt, reverse_current),
        protected_spans_preserved=protected_spans_preserved(prompt, reverse_current),
        ok=ok,
        error=error,
        warning="",
        translatable_span_count=len([s for s in parse_prompt_for_translation(current) if s.translatable and s.value.strip()]),
        changed_translatable_span_count=0,
        no_translatable_span_changed=False,
        prompt_spans=[asdict(s) for s in parse_prompt_for_translation(current)],
        span_results=None,
    ))
    return rows


def read_prompts(path: Path | None) -> List[str]:
    if path is None:
        return list(DEFAULT_PROMPTS)
    if not path.exists():
        raise FileNotFoundError(path)
    prompts = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            prompts.append(line)
    return prompts


def write_json(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run prompt-aware roundtrip translation drift tests.")
    parser.add_argument(
        "--providers",
        nargs="+",
        default=["argos", "nllb", "static_dictionary"],
        help=(
            "Providers to test in sequence. Default avoids 'smart' because smart internally "
            "compares multiple providers and can duplicate model work. Add smart explicitly when needed."
        ),
    )
    parser.add_argument("--languages", nargs="+", default=DEFAULT_ROUNDTRIP_CHAIN, help="Forward language chain, e.g. ja fr de.")
    parser.add_argument("--anchor", default=DEFAULT_ANCHOR_LANGUAGE, help="Original and back-translation language. Default: en.")
    parser.add_argument("--prompts", type=Path, default=None, help="Optional newline-separated prompt test file.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Extension root. Default: parent of language folder.")
    parser.add_argument("--mode", default="prompt", choices=["prompt", "plain"], help="Translation mode.")
    parser.add_argument("--out", type=Path, default=TEST_OUTPUT_DIR / "roundtrip_translation_results.json")
    parser.add_argument("--csv", type=Path, default=TEST_OUTPUT_DIR / "roundtrip_translation_results.csv")
    parser.add_argument("--max-prompts", type=int, default=0, help="Limit prompt count for quick smoke tests. 0 means all prompts.")
    parser.add_argument("--quiet", action="store_true", help="Reduce progress logging.")
    parser.add_argument("--smoke", action="store_true", help="Run a direct provider smoke test before prompt roundtrip tests.")
    parser.add_argument("--smoke-text", default=DEFAULT_SMOKE_TEXT, help="Text used for direct provider smoke tests. Default: cat.")
    parser.add_argument("--clear-provider-cache", action="store_true", help="Clear cached provider instances before each provider test. Use after changing installed models or provider settings.")
    parser.add_argument("--auto-install-python-deps", action="store_true", help="Install missing Python packages needed by selected providers, such as argostranslate.")
    parser.add_argument("--auto-install-models", action="store_true", help="Download/install missing provider model packages needed for the selected language chain when supported. Currently supports Argos language-pair packages.")
    parser.add_argument("--skip-missing-provider-assets", action="store_true", help="Skip a provider when required models/language pairs are missing instead of running and producing unchanged-output warnings.")
    args = parser.parse_args(argv)

    service = PromptTranslatorService(extension_root=args.root)
    prompts = read_prompts(args.prompts)
    if args.max_prompts and args.max_prompts > 0:
        prompts = prompts[: args.max_prompts]
    all_rows: List[Dict[str, Any]] = []

    if not args.quiet:
        print(f"Roundtrip prompts: {len(prompts)}")
        print(f"Providers: {', '.join(args.providers)}")
        print(f"Language chain: {args.anchor} -> {' -> '.join(args.languages)} -> {args.anchor}")
        print("Tip: use --providers argos or --providers nllb to test one model family at a time. Use --max-prompts 1 --smoke for a quick smoke test.")

    for provider in args.providers:
        if args.clear_provider_cache:
            service.clear_provider_cache()
        if not args.quiet:
            print(f"\n=== Provider: {provider} ===")

        provider_preflight_ok = True
        if provider == "argos":
            provider_preflight_ok, preflight_messages = preflight_argos(
                anchor_language=args.anchor,
                languages=args.languages,
                auto_install_python_deps=args.auto_install_python_deps,
                auto_install_models=args.auto_install_models,
                quiet=args.quiet,
            )
            if not args.quiet:
                for message in preflight_messages:
                    print(f"Preflight: {message}")
            if not provider_preflight_ok and args.skip_missing_provider_assets:
                all_rows.append({
                    "provider": provider,
                    "stage_index": -1,
                    "source_language": args.anchor,
                    "target_language": " ".join(args.languages),
                    "input_text": "",
                    "translated_text": "",
                    "back_to_anchor_text": "",
                    "similarity_to_anchor": 0.0,
                    "changed_ratio": 0.0,
                    "protected_spans_preserved": True,
                    "ok": False,
                    "error": "; ".join(preflight_messages),
                    "warning": "provider skipped because required assets are missing",
                    "translatable_span_count": 0,
                    "changed_translatable_span_count": 0,
                    "no_translatable_span_changed": False,
                    "prompt_spans": None,
                    "span_results": None,
                    "prompt_index": 0,
                    "anchor_prompt": "",
                })
                continue
            if not provider_preflight_ok and not args.quiet:
                print("Preflight warning: missing assets may cause unchanged translations.")

        if args.smoke:
            smoke = service.smoke_test_provider(
                provider,
                source_language=args.anchor,
                target_language=args.languages[0] if args.languages else args.anchor,
                text=args.smoke_text,
            )
            if not args.quiet:
                status = "OK" if smoke.get("ok") else "ERROR"
                changed = "changed" if smoke.get("changed") else "unchanged"
                print(f"Smoke {status}: {args.anchor}->{args.languages[0] if args.languages else args.anchor} {args.smoke_text!r} -> {smoke.get('translation')!r} ({changed})")
                if smoke.get("warning"):
                    print(f"  warning: {smoke.get('warning')}")
                if smoke.get("error"):
                    print(f"  error: {smoke.get('error')}")
            smoke_row = {
                "provider": provider,
                "stage_index": 0,
                "source_language": smoke.get("source_language", args.anchor),
                "target_language": smoke.get("target_language", args.languages[0] if args.languages else args.anchor),
                "input_text": smoke.get("input", args.smoke_text),
                "translated_text": smoke.get("translation", args.smoke_text),
                "back_to_anchor_text": "",
                "similarity_to_anchor": 0.0,
                "changed_ratio": 0.0 if smoke.get("changed") is False else 1.0,
                "protected_spans_preserved": True,
                "ok": bool(smoke.get("ok")),
                "error": smoke.get("error", ""),
                "warning": smoke.get("warning", ""),
                "translatable_span_count": 1,
                "changed_translatable_span_count": 1 if smoke.get("changed") else 0,
                "no_translatable_span_changed": bool(smoke.get("ok") and not smoke.get("changed")),
                "prompt_spans": None,
                "span_results": [{
                    "kind": "direct_provider_smoke",
                    "input": smoke.get("input", args.smoke_text),
                    "output": smoke.get("translation", args.smoke_text),
                    "changed": bool(smoke.get("changed")),
                    "provider": provider,
                    "ok": bool(smoke.get("ok")),
                    "error": smoke.get("error", ""),
                    "warning": smoke.get("warning", ""),
                    "models_dir": smoke.get("models_dir", ""),
                }],
                "prompt_index": 0,
                "anchor_prompt": args.smoke_text,
            }
            all_rows.append(smoke_row)
        for prompt_index, prompt in enumerate(prompts, start=1):
            if not args.quiet:
                print(f"Prompt {prompt_index}/{len(prompts)}: {prompt[:90]}")
            rows = run_chain(
                service,
                prompt,
                provider=provider,
                languages=args.languages,
                anchor_language=args.anchor,
                mode=args.mode,
            )
            for row in rows:
                item = asdict(row)
                item["prompt_index"] = prompt_index
                item["anchor_prompt"] = prompt
                all_rows.append(item)

    write_json(args.out, all_rows)
    write_csv(args.csv, all_rows)

    failures = [r for r in all_rows if not r.get("ok") or not r.get("protected_spans_preserved")]
    unchanged_warnings = [r for r in all_rows if r.get("no_translatable_span_changed")]
    print(f"Wrote {len(all_rows)} rows to {args.out}")
    print(f"Wrote CSV to {args.csv}")
    print(f"Failures/protection warnings: {len(failures)}")
    print(f"Unchanged translatable-span warnings: {len(unchanged_warnings)}")
    if unchanged_warnings:
        first = unchanged_warnings[0]
        print("Example unchanged warning:")
        print(f"- provider={first.get('provider')} stage={first.get('stage_index')} {first.get('source_language')}->{first.get('target_language')}")
        print(f"  input : {first.get('input_text')}")
        print(f"  output: {first.get('translated_text')}")
        print("  Parser found translatable spans; inspect span_results in the JSON output.")
    for r in failures[:10]:
        print(f"- provider={r['provider']} prompt={r['prompt_index']} stage={r['stage_index']} error={r.get('error','')}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
