"""
A1111 / Forge extension install bootstrap for the prompt-aware language module.

This script is intentionally lightweight:
- creates folders and starter config files
- installs small Python dependencies when the host provides launch.py
- does NOT auto-download large translation models

Large Argos/NLLB model installs should be done from the UI or by running the
manual commands documented in docs/INSTALL_MODELS.md.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent
LANGUAGE_DIR = ROOT / "language"

REQUIRED_DIRS = [
    LANGUAGE_DIR / "models",
    LANGUAGE_DIR / "models" / "argos",
    LANGUAGE_DIR / "models" / "nllb",
    LANGUAGE_DIR / "dictionaries",
    LANGUAGE_DIR / "cache",
    LANGUAGE_DIR / "config",
]

DEFAULT_FILES = {
    LANGUAGE_DIR / "dictionaries" / "custom_dictionary.json": "{}\n",
    LANGUAGE_DIR / "dictionaries" / "protected_terms.json": "{\n  \"BREAK\": \"BREAK\",\n  \"AND\": \"AND\"\n}\n",
}

# Keep this conservative. Torch is intentionally not listed here because the
# WebUI/Forge environment normally owns the torch install.
REQUIRED_PACKAGES = {
    "argostranslate": "argostranslate",
    "sentencepiece": "sentencepiece",
    "sacremoses": "sacremoses",
    "huggingface_hub": "huggingface-hub",
    "transformers": "transformers",
}


def _module_installed(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _pip_install(packages: Iterable[str]) -> None:
    packages = list(packages)
    if not packages:
        return

    try:
        import launch  # type: ignore
    except Exception:
        cmd = [sys.executable, "-m", "pip", "install", *packages]
        subprocess.check_call(cmd)
        return

    for package in packages:
        if hasattr(launch, "run_pip"):
            launch.run_pip(f"install {package}", f"Installing {package} for prompt-aware translator")
        else:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])


def ensure_directories() -> None:
    for path in REQUIRED_DIRS:
        path.mkdir(parents=True, exist_ok=True)


def ensure_default_files() -> None:
    for path, content in DEFAULT_FILES.items():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")


def ensure_provider_config() -> None:
    config_path = LANGUAGE_DIR / "config" / "provider_config.json"
    if config_path.exists():
        return
    try:
        from language.provider_model_manager import write_provider_config_template
    except Exception:
        return
    write_provider_config_template(config_path)


def install_dependencies() -> None:
    missing = [pkg for module, pkg in REQUIRED_PACKAGES.items() if not _module_installed(module)]
    _pip_install(missing)


def main() -> None:
    ensure_directories()
    ensure_default_files()
    ensure_provider_config()
    install_dependencies()
    print("Prompt-aware translator install bootstrap complete.")
    print("Model installation is manual/on-demand. See docs/INSTALL_MODELS.md.")


if __name__ == "__main__":
    main()
