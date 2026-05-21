from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional

try:
    from ..constants import (
        PROVIDER_ARGOS,
        PROVIDER_DEBUG,
        PROVIDER_DICTIONARY,
        PROVIDER_NLLB,
        PROVIDER_SMART,
        PROVIDER_STATIC_DICTIONARY,
        SUPPORTED_PROVIDERS,
        EXPERIMENTAL_PROVIDERS,
        HIDDEN_PROVIDERS,
    )
except Exception:
    PROVIDER_ARGOS = "argos"
    PROVIDER_NLLB = "nllb"
    PROVIDER_SMART = "smart"
    PROVIDER_DICTIONARY = "dictionary"
    PROVIDER_STATIC_DICTIONARY = "static_dictionary"
    PROVIDER_DEBUG = "debug"

    SUPPORTED_PROVIDERS = {
        PROVIDER_ARGOS,
        PROVIDER_NLLB,
        PROVIDER_SMART,
        PROVIDER_DICTIONARY,
        PROVIDER_STATIC_DICTIONARY,
        PROVIDER_DEBUG,
    }
    EXPERIMENTAL_PROVIDERS = set()
    HIDDEN_PROVIDERS = set()


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    display_name: str
    status: str = "supported"

    provider_class: Optional[type] = None
    factory: Optional[Callable] = None

    module: Optional[str] = None
    class_name: Optional[str] = None

    @property
    def label(self) -> str:
        """Backward-compatible alias for older UI code."""
        return self.display_name


_PROVIDER_ALIASES: Dict[str, str] = {
    "argos": PROVIDER_ARGOS,
    "argostranslate": PROVIDER_ARGOS,
    "argos_translate": PROVIDER_ARGOS,
    "offline_argos": PROVIDER_ARGOS,

    "nllb": PROVIDER_NLLB,
    "nllb200": PROVIDER_NLLB,
    "facebook_nllb": PROVIDER_NLLB,
    "offline_nllb": PROVIDER_NLLB,

    "smart": PROVIDER_SMART,
    "dictionary": PROVIDER_DICTIONARY,
    "dict": PROVIDER_DICTIONARY,
    "static_dictionary": PROVIDER_STATIC_DICTIONARY,
    "static_dict": PROVIDER_STATIC_DICTIONARY,

    "debug": PROVIDER_DEBUG,
    "prefix_debug": PROVIDER_DEBUG,

    "deepl": "deepl",
    "deepl_api": "deepl",
    "openai": "openai",
    "openai_api": "openai",
    "google": "google_cloud",
    "google_translate": "google_cloud",
    "google_cloud": "google_cloud",
}


_PROVIDER_SPECS: Dict[str, ProviderSpec] = {
    PROVIDER_ARGOS: ProviderSpec(
        provider_id=PROVIDER_ARGOS,
        display_name="Argos Translate",
        status="supported",
        module="language.providers.argos_provider",
        class_name="ArgosTranslationProvider",
    ),
    PROVIDER_NLLB: ProviderSpec(
        provider_id=PROVIDER_NLLB,
        display_name="NLLB",
        status="supported",
        module="language.providers.nllb_provider",
        class_name="NLLBTranslationProvider",
    ),
    PROVIDER_SMART: ProviderSpec(
        provider_id=PROVIDER_SMART,
        display_name="Smart",
        status="supported",
        module="language.translation.smart_translate",
        class_name="SmartTranslationProvider",
    ),
    PROVIDER_DICTIONARY: ProviderSpec(
        provider_id=PROVIDER_DICTIONARY,
        display_name="Dictionary",
        status="supported",
        module="language.translation.translation_providers",
        class_name="StaticDictionaryTranslationProvider",
    ),
    PROVIDER_STATIC_DICTIONARY: ProviderSpec(
        provider_id=PROVIDER_STATIC_DICTIONARY,
        display_name="Static Dictionary",
        status="supported",
        module="language.translation.translation_providers",
        class_name="StaticDictionaryTranslationProvider",
    ),
    PROVIDER_DEBUG: ProviderSpec(
        provider_id=PROVIDER_DEBUG,
        display_name="Debug",
        status="supported",
        module="language.translation.translation_providers",
        class_name="DebugTranslationProvider",
    ),

    "deepl": ProviderSpec(
        provider_id="deepl",
        display_name="DeepL",
        status="experimental",
        module="language.providers.deepl_provider",
        class_name="DeepLTranslationProvider",
    ),
    "openai": ProviderSpec(
        provider_id="openai",
        display_name="OpenAI",
        status="experimental",
        module="language.providers.openai_provider",
        class_name="OpenAITranslationProvider",
    ),
    "google_cloud": ProviderSpec(
        provider_id="google_cloud",
        display_name="Google Cloud Translate",
        status="experimental",
        module="language.providers.google_cloud_provider",
        class_name="GoogleCloudTranslationProvider",
    ),
}


PROVIDER_REGISTRY = _PROVIDER_SPECS


def canonical_provider_id(provider_id: str) -> str:
    normalized = str(provider_id or "").strip().casefold()
    return _PROVIDER_ALIASES.get(normalized, normalized)


def get_provider_spec(provider_id: str) -> ProviderSpec | None:
    return _PROVIDER_SPECS.get(canonical_provider_id(provider_id))


def iter_provider_specs(
    *,
    include_experimental: bool = False,
    include_hidden: bool = False,
):
    for provider_id, spec in _PROVIDER_SPECS.items():
        if spec.status == "hidden" and not include_hidden:
            continue
        if spec.status == "experimental" and not include_experimental:
            continue
        if provider_id in HIDDEN_PROVIDERS and not include_hidden:
            continue
        if provider_id in EXPERIMENTAL_PROVIDERS and not include_experimental:
            continue
        yield spec


def supported_provider_ids(include_experimental: bool = False) -> list[str]:
    ids: list[str] = []
    for spec in iter_provider_specs(include_experimental=include_experimental):
        if spec.provider_id in SUPPORTED_PROVIDERS or (
            include_experimental and spec.status == "experimental"
        ):
            ids.append(spec.provider_id)
    return ids


def provider_display_names(include_experimental: bool = False) -> Dict[str, str]:
    return {
        spec.provider_id: spec.display_name
        for spec in iter_provider_specs(include_experimental=include_experimental)
    }
