from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from language_utils import canonical_lang, canonical_mode, detect_language
from prompt_translator_settings import PromptTranslatorSettings, default_settings_path, load_settings, save_settings
from smart_translate import DEFAULT_COMPARE_PROVIDERS, smart_translate_text
from translation_providers import available_providers, get_provider
from prompt_translation_parser import PromptSpan, parse_prompt_for_translation, render_prompt_spans, split_prompt_fragments
from dictionary_manager import (
    dictionary_paths as installed_dictionary_paths,
    download_dictionary_url,
    import_dictionary_file,
    list_installed_dictionaries,
    update_manifest as update_dictionary_manifest,
    write_source_template as write_dictionary_source_template,
)

try:
    from provider_model_manager import (
        DEFAULT_NLLB_MODEL_ID,
        LANGUAGE_NAMES,
        RECOMMENDED_LANGUAGE_CODES,
        asdict as _unused_asdict,  # type: ignore[attr-defined]
    )
except Exception:
    DEFAULT_NLLB_MODEL_ID = "facebook/nllb-200-distilled-600M"
    LANGUAGE_NAMES = {"en": "English", "ja": "Japanese", "es": "Spanish", "fr": "French", "de": "German", "ko": "Korean", "zh": "Chinese"}
    RECOMMENDED_LANGUAGE_CODES = ["en", "ja", "es", "fr", "de", "ko", "zh"]


class PromptTranslatorService:
    """
    UI/app bridge for prompt translation.

    This service is intentionally small and stable so other extensions, such as
    Semantic Prompt, can call it without importing provider/cache internals.
    """

    def __init__(self, *, extension_root: str | Path):
        self.extension_root = Path(extension_root).resolve()
        self.language_dir = self.extension_root / "language"
        self.models_dir = self.language_dir / "models"
        self.cache_dir = self.extension_root / "cache"
        self.config_dir = self.extension_root / "config"
        self.dictionaries_dir = self.language_dir / "dictionaries"
        self.settings_path = default_settings_path(self.extension_root)
        self.settings = load_settings(self.settings_path)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.dictionaries_dir.mkdir(parents=True, exist_ok=True)
        (self.dictionaries_dir / "installed").mkdir(parents=True, exist_ok=True)

    def reload_settings(self) -> Dict[str, Any]:
        self.settings = load_settings(self.settings_path)
        return asdict(self.settings)

    def update_settings(self, **kwargs: Any) -> Dict[str, Any]:
        current = asdict(self.settings)
        for key, value in kwargs.items():
            if key in current and value is not None:
                current[key] = value
        self.settings = PromptTranslatorSettings(**current)
        return save_settings(self.settings_path, self.settings)

    def language_choices(self) -> List[tuple[str, str]]:
        out = []
        for code in RECOMMENDED_LANGUAGE_CODES:
            code2 = canonical_lang(code)
            out.append((code2, LANGUAGE_NAMES.get(code2, code2)))
        return out

    def provider_choices(self) -> List[str]:
        providers = available_providers()
        preferred = ["smart", "static_dictionary", "chain:dict+nllb", "chain:dict+argos", "chain:dict+argos+nllb", "argos", "nllb"]
        out = []
        for p in preferred + providers:
            if p not in out:
                out.append(p)
        return out

    def dictionary_paths(self, *, source_language: str = "", target_language: str = "") -> List[Path]:
        return installed_dictionary_paths(
            self.extension_root,
            source_language=source_language,
            target_language=target_language,
        )

    def dictionary_status(self) -> Dict[str, Any]:
        try:
            manifest = update_dictionary_manifest(self.extension_root)
            return {
                "ok": True,
                "dictionaries_dir": str(self.dictionaries_dir),
                "installed_dir": str(self.dictionaries_dir / "installed"),
                "manifest": manifest,
            }
        except Exception as e:
            return {"ok": False, "error": repr(e), "dictionaries_dir": str(self.dictionaries_dir)}

    def import_dictionary(self, file_path: str, *, source_language: str, target_language: str, name: str = "") -> Dict[str, Any]:
        try:
            info = import_dictionary_file(
                self.extension_root,
                file_path,
                source_language=source_language,
                target_language=target_language,
                name=name,
            )
            return {"ok": True, "dictionary": info.to_dict(), "status": self.dictionary_status()}
        except Exception as e:
            return {"ok": False, "error": repr(e), "file_path": str(file_path)}

    def download_dictionary(self, url: str, *, source_language: str, target_language: str, name: str = "downloaded") -> Dict[str, Any]:
        try:
            info = download_dictionary_url(
                self.extension_root,
                url,
                source_language=source_language,
                target_language=target_language,
                name=name or "downloaded",
            )
            return {"ok": True, "dictionary": info.to_dict(), "status": self.dictionary_status()}
        except Exception as e:
            return {"ok": False, "error": repr(e), "url": str(url)}

    def write_dictionary_sources_template(self) -> Dict[str, Any]:
        try:
            path = write_dictionary_source_template(self.extension_root)
            return {"ok": True, "path": str(path)}
        except Exception as e:
            return {"ok": False, "error": repr(e)}

    def detect_source_language(self, text: str) -> Dict[str, Any]:
        lang, confidence, scores = detect_language(text or "")
        return {"language": lang, "confidence": confidence, "scores": scores}

    def resolve_target_language(self, target_language: Optional[str]) -> str:
        tgt = target_language or self.settings.target_language
        if tgt in {"user", "my_language", "default"}:
            return canonical_lang(self.settings.user_language)
        return canonical_lang(tgt)

    def resolve_source_language(self, text: str, source_language: Optional[str], auto_detect: Optional[bool] = None) -> str:
        auto = self.settings.auto_detect_source if auto_detect is None else bool(auto_detect)
        src = source_language or self.settings.source_language
        if auto or src in {"auto", "detect", ""}:
            return self.detect_source_language(text).get("language") or "und"
        return canonical_lang(src)

    def _providers_for_mode(self, provider: Optional[str]) -> List[str]:
        p = provider or self.settings.provider_mode or "smart"
        if isinstance(p, (list, tuple)) and p:
            p = p[-1]
        p = str(p).strip()
        if p.startswith("(") and p.endswith(")") and "," in p:
            try:
                import ast
                parsed = ast.literal_eval(p)
                if isinstance(parsed, (list, tuple)) and parsed:
                    p = str(parsed[-1])
            except Exception:
                pass
        p = (p or "smart").lower()
        if p == "smart":
            return list(DEFAULT_COMPARE_PROVIDERS)
        return [p]

    def translate_text(
        self,
        text: str,
        *,
        source_language: str = "auto",
        target_language: str = "user",
        provider: str = "smart",
        mode: str = "prompt",
        auto_detect: Optional[bool] = None,
    ) -> Dict[str, Any]:
        text = text or ""
        src = self.resolve_source_language(text, source_language, auto_detect=auto_detect)
        tgt = self.resolve_target_language(target_language)
        mode_key = canonical_mode(mode or self.settings.translation_mode)

        if not text.strip():
            return {"ok": False, "error": "No text provided.", "translation": text, "source_language": src, "target_language": tgt}
        if src == tgt:
            return {"ok": True, "translation": text, "source_language": src, "target_language": tgt, "note": "source and target are the same"}

        providers = self._providers_for_mode(provider)
        dict_paths = self.dictionary_paths(source_language=src, target_language=tgt)

        def _split_prompt_fragments(value: str) -> List[str]:
            # Prompt-safe mode: split only on top-level commas. Commas inside
            # parser structures such as {...}, [...], (...), quotes, and regex
            # spans must stay attached to their fragment.
            return split_prompt_fragments(value)

        def _join_prompt_fragments(parts: List[str]) -> str:
            return ", ".join(p for p in parts if p.strip())

        def _translate_plain(value: str) -> Dict[str, Any]:
            if provider == "smart" or len(providers) > 1:
                result = smart_translate_text(
                    value,
                    source_language=src,
                    target_language=tgt,
                    providers=providers,
                    models_dir=self.models_dir,
                    dictionary_paths=dict_paths,
                    mode=mode_key,
                )
                winner = result.get("winner") or {}
                translated = winner.get("text") or value
                return {
                    "ok": True,
                    "translation": translated,
                    "source_language": src,
                    "target_language": tgt,
                    "provider": winner.get("provider", "smart"),
                    "score": winner.get("score"),
                    "comparison": result,
                }

            try:
                provider_obj = get_provider(providers[0], models_dir=self.models_dir, dictionary_paths=dict_paths)
                translated = provider_obj.translate_texts([value], source_language=src, target_language=tgt)[0]
                return {"ok": True, "translation": translated, "source_language": src, "target_language": tgt, "provider": providers[0]}
            except Exception as e:
                return {"ok": False, "error": repr(e), "translation": value, "source_language": src, "target_language": tgt, "provider": providers[0] if providers else "unknown"}

        def _translate_one(value: str) -> Dict[str, Any]:
            if mode_key != "prompt":
                return _translate_plain(value)

            spans = parse_prompt_for_translation(value)
            translated_spans: List[PromptSpan] = []
            comparisons: List[Dict[str, Any]] = []
            for span in spans:
                if span.translatable and span.value.strip():
                    span_result = _translate_plain(span.value)
                    translated_spans.append(PromptSpan(span.kind, str(span_result.get("translation") or span.value), span.translatable))
                    comparisons.append(span_result.get("comparison") or span_result)
                else:
                    translated_spans.append(span)

            translated = render_prompt_spans(translated_spans)
            protected_values = [span.value for span in spans if not span.translatable and span.value]
            return {
                "ok": True,
                "translation": translated,
                "source_language": src,
                "target_language": tgt,
                "provider": "prompt_span_adapter",
                "protected_spans": protected_values,
                "prompt_spans": [asdict(span) for span in spans],
                "comparison": {
                    "input": value,
                    "fragments": comparisons,
                    "winner": {"provider": "prompt_span_adapter", "text": translated},
                },
            }

        if False and mode_key == "prompt" and "," in text:
            translated_parts: List[str] = []
            comparisons: List[Dict[str, Any]] = []
            for part in _split_prompt_fragments(text):
                part_result = _translate_one(part)
                part_translation = str(part_result.get("translation") or part).strip()
                if not part_translation:
                    part_translation = part
                translated_parts.append(part_translation)
                comparisons.append(part_result.get("comparison") or part_result)

            translated = _join_prompt_fragments(translated_parts)
            return {
                "ok": True,
                "translation": translated,
                "source_language": src,
                "target_language": tgt,
                "provider": "smart_fragmented" if (provider == "smart" or len(providers) > 1) else providers[0],
                "dictionary_paths": [str(p) for p in dict_paths],
                "comparison": {
                    "input": text,
                    "fragments": comparisons,
                    "winner": {"provider": "fragmented", "text": translated},
                },
            }

        result = _translate_one(text)
        result["dictionary_paths"] = [str(p) for p in dict_paths]
        return result

    def translate_values(self, values: Sequence[str], **kwargs: Any) -> List[str]:
        return [self.translate_text(v, **kwargs).get("translation", v) for v in values]

    def compare_providers(
        self,
        text: str,
        *,
        source_language: str = "auto",
        target_language: str = "user",
        providers: Optional[Sequence[str]] = None,
        mode: str = "prompt",
    ) -> Dict[str, Any]:
        src = self.resolve_source_language(text, source_language)
        tgt = self.resolve_target_language(target_language)
        mode = canonical_mode(mode or self.settings.translation_mode)
        return smart_translate_text(
            text or "",
            source_language=src,
            target_language=tgt,
            providers=list(providers or DEFAULT_COMPARE_PROVIDERS),
            models_dir=self.models_dir,
            dictionary_paths=self.dictionary_paths(source_language=src, target_language=tgt),
            mode=canonical_mode(mode or self.settings.translation_mode),
        )

    def replace_selection_payload(
        self,
        selection_payload_json: str,
        *,
        source_language: str = "auto",
        target_language: str = "user",
        provider: str = "smart",
        mode: str = "prompt",
    ) -> Dict[str, Any]:
        try:
            payload = json.loads(selection_payload_json or "{}")
        except Exception:
            payload = {}
        full_text = str(payload.get("value") or "")
        selected_text = str(payload.get("selected_text") or "")
        start = int(payload.get("selection_start") or 0)
        end = int(payload.get("selection_end") or 0)
        if not selected_text and 0 <= start < end <= len(full_text):
            selected_text = full_text[start:end]
        text_to_translate = selected_text or full_text
        result = self.translate_text(text_to_translate, source_language=source_language, target_language=target_language, provider=provider, mode=mode)
        translated = str(result.get("translation") or text_to_translate)
        if selected_text and 0 <= start <= end <= len(full_text):
            updated = full_text[:start] + translated + full_text[end:]
        else:
            updated = translated
        result["updated_prompt"] = updated
        result["selection_start"] = start
        result["selection_end"] = start + len(translated)
        return result

    def provider_status(self) -> Dict[str, Any]:
        try:
            import provider_model_manager as pmm
            return {
                "settings": asdict(self.settings),
                "dictionary_status": self.dictionary_status(),
                "recommended_languages": [{"code": c, "name": pmm.LANGUAGE_NAMES.get(c, c)} for c in pmm.RECOMMENDED_LANGUAGE_CODES],
                "argos_dependency": asdict(pmm.check_argos_dependency()),
                "argos_installed_pairs": [pmm.pair_dict(s, t) for s, t in pmm.get_installed_argos_pairs()],
                "nllb_dependencies": pmm.check_nllb_dependencies(),
                "nllb_models_dir": str(self.models_dir / "nllb"),
                "nllb_lightweight": [asdict(x) for x in pmm.get_nllb_matrix(pmm.get_recommended_pairs("lightweight"), models_dir=self.models_dir)],
            }
        except Exception as e:
            return {"error": repr(e), "settings": asdict(self.settings)}

    def argos_available_matrix(self, *, bundle: str = "lightweight", update_index: bool = True) -> Dict[str, Any]:
        try:
            import provider_model_manager as pmm
            pairs = pmm.get_recommended_pairs(bundle)
            rows = [asdict(x) for x in pmm.get_argos_package_matrix(pairs, update_index=update_index)]
            return {"ok": True, "bundle": bundle, "rows": rows}
        except Exception as e:
            return {"ok": False, "error": repr(e), "bundle": bundle, "rows": []}

    def install_argos_bundle(self, *, bundle: str = "lightweight", stop_on_error: bool = False) -> Dict[str, Any]:
        try:
            import provider_model_manager as pmm
            pairs = pmm.get_recommended_pairs(bundle)
            result = pmm.install_argos_language_bundle(pairs, install_dir=self.models_dir / "argos", stop_on_error=stop_on_error)
            return asdict(result)
        except Exception as e:
            return {"provider": "argos", "errors": [repr(e)], "installed_pairs": [], "skipped_pairs": []}

    def install_argos_pair(self, source_language: str, target_language: str) -> Dict[str, Any]:
        try:
            import provider_model_manager as pmm
            changed = pmm.install_argos_language_pair(source_language, target_language, install_dir=self.models_dir / "argos")
            return {"ok": True, "installed": bool(changed), "source_language": canonical_lang(source_language), "target_language": canonical_lang(target_language)}
        except Exception as e:
            return {"ok": False, "error": repr(e), "source_language": canonical_lang(source_language), "target_language": canonical_lang(target_language)}

    def install_nllb_model(self, *, model_id: str = DEFAULT_NLLB_MODEL_ID, force: bool = False) -> Dict[str, Any]:
        try:
            import provider_model_manager as pmm
            changed = pmm.install_nllb_model(models_dir=self.models_dir, model_id=model_id, force=force)
            return {"ok": True, "installed": bool(changed), "model_id": model_id, "local_path": str(pmm.nllb_local_dir(self.models_dir, model_id))}
        except Exception as e:
            return {"ok": False, "error": repr(e), "model_id": model_id}


def register_a1111_bridge(service: PromptTranslatorService) -> Dict[str, Any]:
    """Register service for other A1111 extensions, especially Semantic Prompt."""
    result = {"shared": False, "module": False}
    try:
        from modules import shared  # type: ignore
        setattr(shared, "semantic_prompt_translator", service)
        result["shared"] = True
    except Exception:
        pass
    try:
        import types
        bridge = types.ModuleType("prompt_translator_bridge")
        bridge.SERVICE = service
        bridge.translate_text = service.translate_text
        bridge.translate_values = service.translate_values
        bridge.compare_providers = service.compare_providers
        bridge.provider_status = service.provider_status
        bridge.dictionary_status = service.dictionary_status
        sys.modules["prompt_translator_bridge"] = bridge
        result["module"] = True
    except Exception:
        pass
    return result


def get_registered_service() -> Optional[PromptTranslatorService]:
    try:
        from modules import shared  # type: ignore
        svc = getattr(shared, "semantic_prompt_translator", None)
        if svc is not None:
            return svc
    except Exception:
        pass
    try:
        import prompt_translator_bridge  # type: ignore
        return getattr(prompt_translator_bridge, "SERVICE", None)
    except Exception:
        return None
