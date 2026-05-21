from __future__ import annotations

"""
Reusable bootstrap helpers for the language module.

Use this from the extension, standalone scripts, or tests to create expected
folders and starter files without installing dependencies or downloading models.
"""

from pathlib import Path
from typing import Dict, Iterable

LANGUAGE_ROOT = Path(__file__).resolve().parent

REQUIRED_DIRS = [
    LANGUAGE_ROOT / "models",
    LANGUAGE_ROOT / "models" / "argos",
    LANGUAGE_ROOT / "models" / "nllb",
    LANGUAGE_ROOT / "dictionaries",
    LANGUAGE_ROOT / "cache",
    LANGUAGE_ROOT / "config",
]

DEFAULT_FILES: Dict[Path, str] = {
    LANGUAGE_ROOT / "dictionaries" / "custom_dictionary.json": "{}\n",
    LANGUAGE_ROOT / "dictionaries" / "protected_terms.json": "{\n  \"BREAK\": \"BREAK\",\n  \"AND\": \"AND\"\n}\n",
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
    config_path = LANGUAGE_ROOT / "config" / "provider_config.json"
    if config_path.exists() and not overwrite:
        return config_path
    try:
        from .provider_model_manager import write_provider_config_template
    except Exception:
        try:
            from provider_model_manager import write_provider_config_template  # type: ignore
        except Exception as exc:
            raise RuntimeError("Could not import provider_model_manager to write provider config") from exc
    write_provider_config_template(config_path)
    return config_path


def bootstrap_language_environment(*, overwrite_config: bool = False) -> Path:
    ensure_directories()
    ensure_default_files()
    return ensure_provider_config(overwrite=overwrite_config)


if __name__ == "__main__":
    path = bootstrap_language_environment()
    print(f"Language environment ready. Provider config: {path}")
