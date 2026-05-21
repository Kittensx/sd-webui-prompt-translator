from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Protocol, Sequence

try:
    from ..paths import INSTALLED_DICTIONARIES_DIR
except ImportError:
    try:
        from language.paths import INSTALLED_DICTIONARIES_DIR
    except ImportError:
        from paths import INSTALLED_DICTIONARIES_DIR

try:
    from language.utils.language_utils import canonical_lang
except Exception:
    from language.utils.language_utils import canonical_lang

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:
    from language.providers.provider_registry import (
        canonical_provider_id,
        get_provider_spec,
        supported_provider_ids,
    )
except Exception:
    from language.providers.provider_registry import (
        canonical_provider_id,
        get_provider_spec,
        supported_provider_ids,
    )


_PROVIDER_INSTANCE_CACHE: Dict[tuple, object] = {}


def _make_cache_key(name: str, kwargs: Dict[str, object]) -> tuple:
    models_dir = str(kwargs.get("models_dir") or "")
    dictionary_paths = tuple(str(p) for p in (kwargs.get("dictionary_paths") or []))
    model_id = str(kwargs.get("model_id") or "")
    local_name = str(kwargs.get("local_name") or "")
    device = str(kwargs.get("device") or "")
    return (name, models_dir, dictionary_paths, model_id, local_name, device)


def clear_provider_cache() -> None:
    """Clear cached provider instances. Useful after installing/removing models."""
    _PROVIDER_INSTANCE_CACHE.clear()


def _cached_provider(name: str, factory, **kwargs):
    key = _make_cache_key(name, kwargs)
    if key not in _PROVIDER_INSTANCE_CACHE:
        _PROVIDER_INSTANCE_CACHE[key] = factory()
    return _PROVIDER_INSTANCE_CACHE[key]


class TranslationProvider(Protocol):
    """Provider interface used by translate_entry/export/search query translation."""
    name: str

    def translate_texts(self, texts: List[str], *, source_language: str, target_language: str) -> List[str]:
        ...


@dataclass
class NoopTranslationProvider:
    """Development provider. It records plumbing without changing text."""
    name: str = "noop"

    def translate_texts(self, texts: List[str], *, source_language: str, target_language: str) -> List[str]:
        return list(texts)


@dataclass
class PrefixDebugTranslationProvider:
    """Useful for UI tests because translated output is visibly different."""
    name: str = "prefix_debug"

    def translate_texts(self, texts: List[str], *, source_language: str, target_language: str) -> List[str]:
        target = canonical_lang(target_language)
        return [f"[{target}] {t}" for t in texts]


class StaticDictionaryTranslationProvider:
    """
    Local dictionary/glossary provider.

    Dictionaries are optional JSON or TSV/TXT files. Supported JSON shapes:
      1) Flat pair map, when loaded with pair context by dictionary_manager:
         {"riverbank": "川岸"}
      2) Nested pair map:
         {"en": {"ja": {"riverbank": "川岸"}}}
      3) Records:
         [{"source_language":"en", "target_language":"ja", "source":"riverbank", "target":"川岸"}]

    Unknown strings pass through unchanged. Exact match is preferred, then
    stripped/casefolded match for prompt fragments like "duck".
    """
    name = "static_dictionary"

    def __init__(self, dictionary: Dict[tuple[str, str, str], str] | None = None, dictionary_paths: Sequence[str | Path] | None = None):
        self.dictionary: Dict[tuple[str, str, str], str] = dictionary or {}
        # Keep tiny examples for smoke tests only. Real dictionaries are installed
        # under the top-level dictionaries/installed folder and loaded through dictionary_paths.
        defaults = {
            ("ja", "en", "川岸"): "riverbank",
            ("ja", "en", "河原"): "riverbed",
            ("ja", "en", "桜"): "cherry blossoms",
            ("en", "ja", "riverbank"): "川岸",
            ("en", "ja", "river shore"): "川岸",
            ("es", "en", "orilla del río"): "riverbank",
            ("en", "es", "riverbank"): "orilla del río",
        }
        for key, value in defaults.items():
            self._set(*key, value)
        for path in dictionary_paths or []:
            self.load_dictionary_file(Path(path))

    def _norm_source(self, text: str) -> str:
        return " ".join(str(text or "").strip().split()).casefold()

    def _set(self, src: str, tgt: str, source: str, target: str) -> None:
        src = canonical_lang(src)
        tgt = canonical_lang(tgt)
        source = str(source or "").strip()
        target = str(target or "").strip()
        if not source or not target or src == "und" or tgt == "und":
            return
        self.dictionary[(src, tgt, source)] = target
        self.dictionary[(src, tgt, self._norm_source(source))] = target

    def load_dictionary_file(self, path: Path) -> None:
        if not path.exists():
            return
        suffix = path.suffix.lower()
        if suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for rec in data:
                    if not isinstance(rec, dict):
                        continue
                    src = canonical_lang(str(rec.get("source_language") or rec.get("src") or ""))
                    tgt = canonical_lang(str(rec.get("target_language") or rec.get("tgt") or ""))
                    source = rec.get("source") or rec.get("term") or rec.get("headword")
                    target = rec.get("target") or rec.get("translation") or rec.get("definition") or rec.get("gloss")
                    if isinstance(source, str) and isinstance(target, str):
                        self._set(src, tgt, source, target)
                return
            if isinstance(data, dict):
                nested_used = False
                for src, tgt_map in data.items():
                    if not isinstance(tgt_map, dict):
                        continue
                    for tgt, pairs in tgt_map.items():
                        if not isinstance(pairs, dict):
                            continue
                        nested_used = True
                        for source, target in pairs.items():
                            if isinstance(source, str):
                                if isinstance(target, list):
                                    target = next((x for x in target if isinstance(x, str) and x.strip()), "")
                                if isinstance(target, str):
                                    self._set(str(src), str(tgt), source, target)
                if nested_used:
                    return
            return

        # TSV/TXT fallback. File name should start src_tgt, e.g. en_ja.wikdict.tsv.
        src = tgt = "und"
        stem = path.name.lower()
        if len(stem) >= 5 and "_" in stem:
            left = stem.split(".", 1)[0]
            parts = left.split("_", 1)
            if len(parts) == 2:
                src, tgt = canonical_lang(parts[0]), canonical_lang(parts[1])
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "\t" in line:
                source, target = line.split("\t", 1)
            elif " = " in line:
                source, target = line.split(" = ", 1)
            elif "," in line:
                source, target = line.split(",", 1)
            else:
                continue
            self._set(src, tgt, source, target)

    def load_pair_dictionary(self, path: Path, *, source_language: str, target_language: str) -> None:
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        src = canonical_lang(source_language)
        tgt = canonical_lang(target_language)
        for source, target in data.items():
            if isinstance(target, list):
                target = next((x for x in target if isinstance(x, str) and x.strip()), "")
            if isinstance(source, str) and isinstance(target, str):
                self._set(src, tgt, source, target)

    def translate_texts(self, texts: List[str], *, source_language: str, target_language: str) -> List[str]:
        src = canonical_lang(source_language)
        tgt = canonical_lang(target_language)
        out: List[str] = []
        for t in texts:
            raw = str(t or "")
            value = self.dictionary.get((src, tgt, raw))
            if value is None:
                value = self.dictionary.get((src, tgt, raw.strip()))
            if value is None:
                value = self.dictionary.get((src, tgt, self._norm_source(raw)))
            out.append(value if isinstance(value, str) and value else raw)
        return out


@dataclass
class CompositeTranslationProvider:
    """Tries providers in order. If a provider returns a changed string, that value wins."""
    providers: List[TranslationProvider]
    name: str = "composite"

    def translate_texts(self, texts: List[str], *, source_language: str, target_language: str) -> List[str]:
        remaining = list(texts)
        final = list(texts)
        unresolved_indices = list(range(len(texts)))

        for provider in self.providers:
            if not unresolved_indices:
                break
            batch = [remaining[i] for i in unresolved_indices]
            translated = provider.translate_texts(batch, source_language=source_language, target_language=target_language)
            next_unresolved: List[int] = []
            for local_i, global_i in enumerate(unresolved_indices):
                original = remaining[global_i]
                candidate = translated[local_i] if local_i < len(translated) else original
                if isinstance(candidate, str) and candidate != original:
                    final[global_i] = candidate
                else:
                    next_unresolved.append(global_i)
            unresolved_indices = next_unresolved
        return final


def _filtered_kwargs_for_class(cls, kwargs: Dict[str, object]) -> Dict[str, object]:
    """
    Provider constructors intentionally differ. For example:
      - Argos does not need models_dir.
      - NLLB needs models_dir but does not need dictionary_paths.
      - Cloud providers may only need api_key/env options.

    This helper lets smart_translate pass shared app context without breaking
    providers that do not accept every option. If a plugin declares **kwargs,
    we pass everything through.
    """
    try:
        sig = inspect.signature(cls)
    except Exception:
        return dict(kwargs)

    params = sig.parameters
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(kwargs)

    allowed = {
        name
        for name, param in params.items()
        if name != "self"
        and param.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }
    return {k: v for k, v in kwargs.items() if k in allowed}


def _provider_from_plugin(module_name: str, class_name: str = "Provider", **kwargs) -> TranslationProvider:
    """
    Import provider plugins from the canonical language.providers namespace.

    The project previously supported a top-level providers/ folder as a fallback,
    but that created duplicate modules and stale import risk. Keep provider files
    under language/providers/ and import through the registry.
    """
    for candidate in (ROOT, HERE):
        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)

    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            f"Could not import provider module {module_name!r}. "
            "Provider files should live under language/providers/."
        ) from e

    cls = getattr(module, class_name)
    return cls(**_filtered_kwargs_for_class(cls, kwargs))


def _provider_from_registry(provider_id: str, **kwargs) -> TranslationProvider:
    spec = get_provider_spec(provider_id)

    module = getattr(spec, "module", None) or getattr(spec, "module_path", None)
    class_name = getattr(spec, "class_name", None)

    if module and class_name:
        return _provider_from_plugin(module, class_name, **kwargs)

    provider_class = getattr(spec, "provider_class", None)
    if provider_class is not None:
        return provider_class(**kwargs)

    factory = getattr(spec, "factory", None)
    if factory is not None:
        return factory(**kwargs)

    raise AttributeError(
        f"ProviderSpec for {provider_id!r} does not define module/class_name, "
        "provider_class, or factory."
    )

def available_providers(include_experimental: bool = False) -> List[str]:
    return [
        "noop",
        "debug",
        "static_dictionary",
        *supported_provider_ids(include_experimental=include_experimental),
        "chain:dict+nllb",
        "chain:dict+argos",
        "chain:dict+argos+nllb",
    ]

def get_provider(name: str | None, **kwargs) -> TranslationProvider:
    """
    Provider factory.

    No cloud provider is enabled unless explicitly selected and configured.
    API keys should come from environment variables, not source files.
    """
    provider = canonical_provider_id(name)

    if provider in {"noop", "none"}:
        return NoopTranslationProvider()
    if provider in {"debug", "prefix_debug"}:
        return PrefixDebugTranslationProvider()
    if provider in {"dict", "static", "static_dictionary", "dictionary"}:
        paths = kwargs.get("dictionary_paths") or []
        return _cached_provider("static_dictionary", lambda: StaticDictionaryTranslationProvider(dictionary_paths=paths), **kwargs)
    if provider in {"argos", "argos_translate", "offline_argos"}:
        return _cached_provider("argos", lambda: _provider_from_registry("argos", **kwargs), **kwargs)
    if provider in {"deepl", "deepl_api"}:
        return _provider_from_registry("deepl", **kwargs)
    if provider in {"openai", "openai_api"}:
        return _provider_from_registry("openai", **kwargs)
    if provider in {"google", "google_cloud", "google_translate"}:
        return _provider_from_registry("google_cloud", **kwargs)
    if provider in {"nllb", "nllb200", "facebook_nllb", "offline_nllb"}:
        return _cached_provider("nllb", lambda: _provider_from_registry("nllb", **kwargs), **kwargs)
    if provider in {"marian", "marianmt", "huggingface_marian", "hf_marian"}:
        raise ValueError(
            "Marian is no longer included as an official provider because prompt-fragment tests showed high hallucination risk. "
            "Use Argos or NLLB, or add Marian as a user/community provider plugin if desired."
        )
    if provider in {"chain:dict+nllb", "dictionary+nllb", "dict+nllb"}:
        return _cached_provider("chain:dict+nllb", lambda: CompositeTranslationProvider([
            get_provider("static_dictionary", **kwargs),
            get_provider("nllb", **kwargs),
        ]), **kwargs)
    if provider in {"chain:dict+argos", "dictionary+argos", "dict+argos"}:
        return _cached_provider("chain:dict+argos", lambda: CompositeTranslationProvider([
            get_provider("static_dictionary", **kwargs),
            get_provider("argos", **kwargs),
        ]), **kwargs)
    if provider in {"chain:dict+argos+nllb", "dictionary+argos+nllb", "dict+argos+nllb"}:
        return _cached_provider("chain:dict+argos+nllb", lambda: CompositeTranslationProvider([
            get_provider("static_dictionary", **kwargs),
            get_provider("argos", **kwargs),
            get_provider("nllb", **kwargs),
        ]), **kwargs)
    raise ValueError(f"Unknown translation provider: {name!r}. Available: {', '.join(available_providers())}")
