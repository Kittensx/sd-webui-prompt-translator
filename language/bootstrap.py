from __future__ import annotations

"""
Reusable bootstrap helpers for the language module.

Creates expected runtime folders and starter files without installing dependencies
or downloading large models.
"""

from pathlib import Path
from typing import Dict, Iterable

try:
    from .constants import PROTECTED_KEYWORD_AND, PROTECTED_KEYWORD_BREAK
    from .paths import (
        ALL_RUNTIME_DIRS,
        CUSTOM_DICTIONARY_PATH,
        PROTECTED_TERMS_PATH,
        PROVIDER_CONFIG_PATH,
    )
except ImportError:
    try:
        from language.constants import PROTECTED_KEYWORD_AND, PROTECTED_KEYWORD_BREAK
        from language.paths import (
            ALL_RUNTIME_DIRS,
            CUSTOM_DICTIONARY_PATH,
            PROTECTED_TERMS_PATH,
            PROVIDER_CONFIG_PATH,
        )
    except ImportError:
        from constants import PROTECTED_KEYWORD_AND, PROTECTED_KEYWORD_BREAK
        from paths import (
            ALL_RUNTIME_DIRS,
            CUSTOM_DICTIONARY_PATH,
            PROTECTED_TERMS_PATH,
            PROVIDER_CONFIG_PATH,
        )

REQUIRED_DIRS = ALL_RUNTIME_DIRS

DEFAULT_FILES: Dict[Path, str] = {
    CUSTOM_DICTIONARY_PATH: "{}\n",
    PROTECTED_TERMS_PATH: (
        "{\n"
        f'  "{PROTECTED_KEYWORD_BREAK}": "{PROTECTED_KEYWORD_BREAK}",\n'
        f'  "{PROTECTED_KEYWORD_AND}": "{PROTECTED_KEYWORD_AND}"\n'
        "}\n"
    ),
}


def ensure_directories(paths: Iterable[Path] | None = None) -> None:
    for path in paths or REQUIRED_DIRS:
        Path(path).mkdir(parents=True, exist_ok=True)


def ensure_default_files(files: Dict[Path, str] | None = None, *, overwrite: bool = False) -> None:
    for path, content in (files or DEFAULT_FILES).items():
        path = Path(path)
        if overwrite or not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")


def ensure_provider_config(*, overwrite: bool = False) -> Path:
    config_path = PROVIDER_CONFIG_PATH
    if config_path.exists() and not overwrite:
        return config_path
    try:
        from .provider_model_manager import write_provider_config_template
    except Exception:
        try:
            from language.provider_model_manager import write_provider_config_template
        except Exception:
            from language.providers.provider_model_manager import write_provider_config_template  # type: ignore
    write_provider_config_template(config_path)
    return config_path


def bootstrap_language_environment(*, overwrite_config: bool = False) -> Path:
    ensure_directories()
    ensure_default_files()
    return ensure_provider_config(overwrite=overwrite_config)


if __name__ == "__main__":
    path = bootstrap_language_environment()
    print(f"Language environment ready. Provider config: {path}")
