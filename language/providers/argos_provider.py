from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from language_utils import canonical_lang


@dataclass
class Provider:
    """
    Offline Argos Translate provider.

    Requires optional dependency:
      pip install argostranslate

    Language models are installed separately. Use provider_model_manager.py from
    the app/UI to install recommended pairs or user-selected pairs.
    """
    name: str = "argos"
    fallback_to_original: bool = True

    def is_available(self) -> bool:
        try:
            import argostranslate  # noqa: F401
            return True
        except Exception:
            return False

    def installed_pairs(self) -> List[Tuple[str, str]]:
        try:
            from provider_model_manager import get_installed_argos_pairs
            return get_installed_argos_pairs()
        except Exception:
            return []

    def supports_pair(self, source_language: str, target_language: str) -> bool:
        src = canonical_lang(source_language)
        tgt = canonical_lang(target_language)
        return (src, tgt) in set(self.installed_pairs())

    def _translate_one(self, text: str, source_language: str, target_language: str) -> str:
        try:
            from argostranslate import translate
        except Exception as e:
            if self.fallback_to_original:
                return text
            raise RuntimeError("Argos provider requires: pip install argostranslate") from e

        src = canonical_lang(source_language)
        tgt = canonical_lang(target_language)
        try:
            installed_languages = translate.get_installed_languages()
            from_lang = next((l for l in installed_languages if l.code == src), None)
            to_lang = next((l for l in installed_languages if l.code == tgt), None)
            if from_lang is None or to_lang is None:
                if self.fallback_to_original:
                    return text
                raise RuntimeError(f"Argos language package not installed for {src}->{tgt}")
            translation = from_lang.get_translation(to_lang)
            return translation.translate(text)
        except Exception:
            if self.fallback_to_original:
                return text
            raise

    def translate_texts(self, texts: List[str], *, source_language: str, target_language: str) -> List[str]:
        return [self._translate_one(t, source_language, target_language) for t in texts]
