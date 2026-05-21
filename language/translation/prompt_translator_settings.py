from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict

try:
    from ..constants import DEFAULT_NLLB_MODEL_ID, PROVIDER_ID_SMART
    from ..paths import CONFIG_DIR
except ImportError:
    try:
        from language.constants import DEFAULT_NLLB_MODEL_ID, PROVIDER_ID_SMART
        from language.paths import CONFIG_DIR
    except ImportError:
        from constants import DEFAULT_NLLB_MODEL_ID, PROVIDER_ID_SMART
        from paths import CONFIG_DIR


@dataclass
class PromptTranslatorSettings:
    user_language: str = "en"
    source_language: str = "auto"
    target_language: str = "user"
    provider_mode: str = PROVIDER_ID_SMART  # smart | argos | nllb | static_dictionary | etc.
    translation_mode: str = "prompt"  # prompt | natural_language | search
    auto_detect_source: bool = True
    cache_enabled: bool = True
    show_provider_comparison: bool = True
    prefer_replace_selection: bool = True
    argos_bundle: str = "lightweight"
    nllb_model: str = DEFAULT_NLLB_MODEL_ID


def default_settings_path(extension_root: Path) -> Path:
    return CONFIG_DIR / "language_settings.json"


def load_settings(path: Path) -> PromptTranslatorSettings:
    path = Path(path)
    if not path.exists():
        return PromptTranslatorSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return PromptTranslatorSettings()
    if not isinstance(data, dict):
        return PromptTranslatorSettings()
    base = asdict(PromptTranslatorSettings())
    base.update({k: v for k, v in data.items() if k in base})
    return PromptTranslatorSettings(**base)


def save_settings(path: Path, settings: PromptTranslatorSettings) -> Dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(settings)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def settings_to_dict(settings: PromptTranslatorSettings) -> Dict[str, Any]:
    return asdict(settings)
