from __future__ import annotations

"""
provider_model_manager.py

Optional provider dependency/model installer for Semantic Pack Language backend.

Official offline providers:
- Argos Translate: small language-pair packages, good literal default.
- NLLB: one multilingual Hugging Face model, stronger optional offline provider.

Marian is intentionally not included in official defaults because prompt-fragment
translation tests showed high hallucination risk. Users can add it as a custom
provider plugin if they want.
"""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from language_utils import canonical_lang
except Exception:
    from .language_utils import canonical_lang

RECOMMENDED_LANGUAGE_CODES: List[str] = [
    "en", "ja", "es", "fr", "de", "it", "pt", "ko", "zh", "ru", "ar", "hi", "nl", "pl", "tr", "id", "vi", "th",
]

LANGUAGE_NAMES: Dict[str, str] = {
    "en": "English", "ja": "Japanese", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
    "pt": "Portuguese", "ko": "Korean", "zh": "Chinese", "ru": "Russian", "ar": "Arabic", "hi": "Hindi",
    "nl": "Dutch", "pl": "Polish", "tr": "Turkish", "id": "Indonesian", "vi": "Vietnamese", "th": "Thai",
}

LIGHTWEIGHT_PAIRS: List[Tuple[str, str]] = [
    ("en", "ja"), ("ja", "en"),
    ("en", "es"), ("es", "en"),
    ("en", "fr"), ("fr", "en"),
    ("en", "de"), ("de", "en"),
    ("en", "ko"), ("ko", "en"),
    ("en", "zh"), ("zh", "en"),
]

FULL_ENGLISH_PIVOT_PAIRS: List[Tuple[str, str]] = []
for _lang in RECOMMENDED_LANGUAGE_CODES:
    if _lang == "en":
        continue
    FULL_ENGLISH_PIVOT_PAIRS.append(("en", _lang))
    FULL_ENGLISH_PIVOT_PAIRS.append((_lang, "en"))

DEFAULT_NLLB_MODEL_ID = "facebook/nllb-200-distilled-600M"
NLLB_MODEL_IDS: Dict[str, str] = {
    "600m": "facebook/nllb-200-distilled-600M",
    "1.3b": "facebook/nllb-200-distilled-1.3B",
}


@dataclass
class ProviderInstallStatus:
    provider: str
    python_package: str
    installed: bool
    version: Optional[str] = None
    import_error: Optional[str] = None


@dataclass
class PairInfo:
    source_language: str
    target_language: str
    provider: str
    installed: bool = False
    available: bool = False
    notes: str = ""
    model_id: str = ""
    local_path: str = ""


@dataclass
class InstallResult:
    provider: str
    requested_pairs: List[Dict[str, str]]
    installed_pairs: List[Dict[str, str]]
    skipped_pairs: List[Dict[str, str]]
    errors: List[str]
    install_dir: Optional[str] = None
    generated_at: str = ""
    model_id: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def pair_dict(src: str, tgt: str) -> Dict[str, str]:
    return {"source_language": canonical_lang(src), "target_language": canonical_lang(tgt)}


def normalize_pairs(pairs: Iterable[Tuple[str, str] | Sequence[str] | str]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    seen = set()
    for item in pairs:
        src = tgt = ""
        if isinstance(item, str):
            if ":" in item:
                src, tgt = item.split(":", 1)
            elif "-" in item:
                src, tgt = item.split("-", 1)
        else:
            values = list(item)
            if len(values) >= 2:
                src, tgt = str(values[0]), str(values[1])
        src = canonical_lang(src)
        tgt = canonical_lang(tgt)
        if src == "und" or tgt == "und" or src == tgt:
            continue
        key = (src, tgt)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def get_recommended_pairs(bundle: str = "lightweight") -> List[Tuple[str, str]]:
    b = (bundle or "lightweight").strip().lower()
    if b in {"light", "lite", "small", "lightweight", "starter"}:
        return list(LIGHTWEIGHT_PAIRS)
    if b in {"all", "full", "recommended"}:
        return list(FULL_ENGLISH_PIVOT_PAIRS)
    raise ValueError("Unknown language bundle. Use lightweight or full.")


def check_python_package(module_name: str, package_name: Optional[str] = None) -> ProviderInstallStatus:
    package_name = package_name or module_name
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return ProviderInstallStatus(module_name, package_name, False, import_error=f"Module not found: {module_name}")
    try:
        mod = __import__(module_name)
        version = getattr(mod, "__version__", None)
    except Exception as e:
        return ProviderInstallStatus(module_name, package_name, False, import_error=repr(e))
    return ProviderInstallStatus(module_name, package_name, True, str(version) if version else None)


def install_python_packages(packages: Sequence[str], *, python_executable: Optional[str] = None, upgrade: bool = False) -> int:
    exe = python_executable or sys.executable
    cmd = [exe, "-m", "pip", "install"]
    if upgrade:
        cmd.append("--upgrade")
    cmd.extend(packages)
    return subprocess.call(cmd)


# -----------------------------
# Argos
# -----------------------------

def check_argos_dependency() -> ProviderInstallStatus:
    return check_python_package("argostranslate", "argostranslate")


def install_argos_dependency(*, python_executable: Optional[str] = None, upgrade: bool = False) -> int:
    return install_python_packages(["argostranslate"], python_executable=python_executable, upgrade=upgrade)


def _get_argos_modules():
    try:
        from argostranslate import package, translate
    except Exception as e:
        raise RuntimeError("Argos Translate is not installed. Install with: pip install argostranslate") from e
    return package, translate


def get_installed_argos_pairs() -> List[Tuple[str, str]]:
    try:
        _package, translate = _get_argos_modules()
        pairs: List[Tuple[str, str]] = []
        for from_lang in translate.get_installed_languages():
            for to_lang in translate.get_installed_languages():
                if from_lang.code == to_lang.code:
                    continue
                try:
                    from_lang.get_translation(to_lang)
                    pairs.append((canonical_lang(from_lang.code), canonical_lang(to_lang.code)))
                except Exception:
                    pass
        return sorted(set(pairs))
    except Exception:
        return []


def _pkg_attr(pkg: Any, *names: str) -> str:
    for name in names:
        value = getattr(pkg, name, None)
        if value is not None:
            return str(value)
    return ""


def get_available_argos_packages(*, update_index: bool = True) -> List[Any]:
    package, _translate = _get_argos_modules()
    if update_index:
        package.update_package_index()
    return list(package.get_available_packages())


def find_available_argos_package(source_language: str, target_language: str, *, update_index: bool = True) -> Optional[Any]:
    src = canonical_lang(source_language)
    tgt = canonical_lang(target_language)
    for pkg in get_available_argos_packages(update_index=update_index):
        from_code = canonical_lang(_pkg_attr(pkg, "from_code", "source_code", "source_language", "from_lang"))
        to_code = canonical_lang(_pkg_attr(pkg, "to_code", "target_code", "target_language", "to_lang"))
        if from_code == src and to_code == tgt:
            return pkg
    return None


def get_argos_package_matrix(pairs: Optional[Iterable[Tuple[str, str]]] = None, *, update_index: bool = False) -> List[PairInfo]:
    requested = normalize_pairs(pairs or get_recommended_pairs("lightweight"))
    installed = set(get_installed_argos_pairs())
    available_by_pair: Dict[Tuple[str, str], Any] = {}
    try:
        for pkg in get_available_argos_packages(update_index=update_index):
            src = canonical_lang(_pkg_attr(pkg, "from_code", "source_code", "source_language", "from_lang"))
            tgt = canonical_lang(_pkg_attr(pkg, "to_code", "target_code", "target_language", "to_lang"))
            if src != "und" and tgt != "und":
                available_by_pair[(src, tgt)] = pkg
    except Exception:
        pass
    return [
        PairInfo(src, tgt, "argos", (src, tgt) in installed, (src, tgt) in available_by_pair,
                 "installed" if (src, tgt) in installed else ("available" if (src, tgt) in available_by_pair else "not found in index"))
        for src, tgt in requested
    ]


def install_argos_language_pair(source_language: str, target_language: str, *, install_dir: Optional[str | Path] = None, update_index: bool = True) -> bool:
    package, _translate = _get_argos_modules()
    src = canonical_lang(source_language)
    tgt = canonical_lang(target_language)
    if (src, tgt) in set(get_installed_argos_pairs()):
        return False
    pkg = find_available_argos_package(src, tgt, update_index=update_index)
    if pkg is None:
        raise RuntimeError(f"No Argos package found for {src}->{tgt}")
    try:
        download_path = pkg.download()
    except TypeError:
        if not install_dir:
            raise
        base = Path(install_dir).expanduser().resolve()
        base.mkdir(parents=True, exist_ok=True)
        download_path = pkg.download(str(base))
    if not download_path:
        for attr in ("download_path", "package_path", "local_path", "path"):
            candidate = getattr(pkg, attr, None)
            if candidate:
                download_path = candidate
                break
    if not download_path:
        raise RuntimeError(f"Argos downloaded {src}->{tgt}, but did not return a model path")
    download_path = Path(download_path).expanduser().resolve()
    if install_dir:
        base = Path(install_dir).expanduser().resolve()
        base.mkdir(parents=True, exist_ok=True)
        dest = base / download_path.name
        if download_path.exists() and download_path.resolve() != dest.resolve():
            try:
                shutil.copy2(download_path, dest)
            except Exception:
                pass
    package.install_from_path(str(download_path))
    return True


def install_argos_language_bundle(pairs: Iterable[Tuple[str, str]], *, install_dir: Optional[str | Path] = None, stop_on_error: bool = False) -> InstallResult:
    requested = normalize_pairs(pairs)
    result = InstallResult("argos", [pair_dict(s, t) for s, t in requested], [], [], [], str(Path(install_dir).expanduser().resolve()) if install_dir else None, utc_now())
    try:
        package, _translate = _get_argos_modules()
        package.update_package_index()
    except Exception as e:
        result.errors.append(f"Could not update Argos package index: {e!r}")
        if stop_on_error:
            return result
    for src, tgt in requested:
        try:
            changed = install_argos_language_pair(src, tgt, install_dir=install_dir, update_index=False)
            if changed:
                result.installed_pairs.append(pair_dict(src, tgt))
            else:
                result.skipped_pairs.append({**pair_dict(src, tgt), "reason": "already_installed"})
        except Exception as e:
            result.errors.append(f"{src}->{tgt}: {e!r}")
            if stop_on_error:
                break
    return result


# -----------------------------
# NLLB
# -----------------------------

def safe_model_name(model_id: str) -> str:
    return model_id.replace("/", "_")


def nllb_model_id(size: str | None = None, model: str | None = None) -> str:
    if model:
        return model
    return NLLB_MODEL_IDS.get((size or "600m").lower(), DEFAULT_NLLB_MODEL_ID)


def nllb_local_dir(models_dir: str | Path, model_id: str = DEFAULT_NLLB_MODEL_ID) -> Path:
    return Path(models_dir).expanduser().resolve() / "nllb" / safe_model_name(model_id)


def check_nllb_dependencies() -> Dict[str, Any]:
    return {
        "transformers": asdict(check_python_package("transformers", "transformers")),
        "sentencepiece": asdict(check_python_package("sentencepiece", "sentencepiece")),
        "huggingface_hub": asdict(check_python_package("huggingface_hub", "huggingface_hub")),
        "torch": asdict(check_python_package("torch", "torch")),
    }


def install_nllb_dependencies(*, python_executable: Optional[str] = None, upgrade: bool = False, include_torch: bool = False) -> int:
    packages = ["transformers", "sentencepiece", "huggingface_hub"]
    if include_torch:
        packages.append("torch")
    return install_python_packages(packages, python_executable=python_executable, upgrade=upgrade)


def install_nllb_model(*, models_dir: str | Path = "semantic/language/models", model_id: str = DEFAULT_NLLB_MODEL_ID, force: bool = False, revision: Optional[str] = None) -> bool:
    local = nllb_local_dir(models_dir, model_id)
    if local.exists() and any(local.iterdir()) and not force:
        return False
    local.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
    except Exception as e:
        raise RuntimeError("NLLB model install requires huggingface_hub. Install with: pip install huggingface_hub transformers sentencepiece") from e
    kwargs: Dict[str, Any] = {
        "repo_id": model_id,
        "local_dir": str(local),
        "local_dir_use_symlinks": False,
        "ignore_patterns": ["*.h5", "*.ot", "*.msgpack", "*.onnx", "*.tflite"],
    }
    token = os.getenv("HF_TOKEN")
    if token:
        kwargs["token"] = token
    if revision:
        kwargs["revision"] = revision
    snapshot_download(**kwargs)
    return True


def get_nllb_matrix(pairs: Optional[Iterable[Tuple[str, str]]] = None, *, models_dir: str | Path = "semantic/language/models", model_id: str = DEFAULT_NLLB_MODEL_ID) -> List[PairInfo]:
    requested = normalize_pairs(pairs or get_recommended_pairs("lightweight"))
    local = nllb_local_dir(models_dir, model_id)
    installed = local.exists() and any(local.iterdir())
    return [
        PairInfo(src, tgt, "nllb", installed, True, "installed" if installed else "model not downloaded", model_id=model_id, local_path=str(local))
        for src, tgt in requested
    ]


def install_nllb_bundle(pairs: Iterable[Tuple[str, str]], *, models_dir: str | Path = "semantic/language/models", model_id: str = DEFAULT_NLLB_MODEL_ID, force: bool = False) -> InstallResult:
    requested = normalize_pairs(pairs)
    local = nllb_local_dir(models_dir, model_id)
    result = InstallResult("nllb", [pair_dict(s, t) for s, t in requested], [], [], [], str(local), utc_now(), model_id=model_id)
    try:
        changed = install_nllb_model(models_dir=models_dir, model_id=model_id, force=force)
        if changed:
            result.installed_pairs = [pair_dict(s, t) for s, t in requested]
        else:
            result.skipped_pairs = [{**pair_dict(s, t), "reason": "model_already_installed"} for s, t in requested]
    except Exception as e:
        result.errors.append(repr(e))
    return result


def write_provider_config_template(path: Path) -> Dict[str, Any]:
    config = {
        "version": 2,
        "default_provider_chain": ["static_dictionary", "argos", "nllb"],
        "official_offline_providers": ["argos", "nllb"],
        "excluded_from_official_defaults": {"marian": "Removed from official stack due to prompt-fragment hallucination risk."},
        "cloud_fallback_enabled": False,
        "recommended_language_codes": RECOMMENDED_LANGUAGE_CODES,
        "starter_bundle": {"name": "lightweight", "pairs": [pair_dict(s, t) for s, t in LIGHTWEIGHT_PAIRS]},
        "full_bundle": {"name": "full", "pairs": [pair_dict(s, t) for s, t in FULL_ENGLISH_PIVOT_PAIRS]},
        "argos": {"python_package": "argostranslate", "models_dir": "semantic/language/models/argos", "auto_install_dependency": False, "auto_download_models": False},
        "nllb": {"python_packages": ["transformers", "sentencepiece", "huggingface_hub"], "models_dir": "semantic/language/models", "default_model": DEFAULT_NLLB_MODEL_ID, "auto_install_dependency": False, "auto_download_models": False, "install_torch": False},
        "quality": {"enabled": True, "mode": "prompt", "compare_providers": ["static_dictionary", "argos", "nllb"]},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return config


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Manage optional translation provider packages and language models.")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("status")

    p_matrix = sub.add_parser("matrix", help="Show Argos language pair install matrix.")
    p_matrix.add_argument("--bundle", choices=["lightweight", "full"], default="lightweight")
    p_matrix.add_argument("--update-index", action="store_true")

    p_install_dep = sub.add_parser("install-argos")
    p_install_dep.add_argument("--upgrade", action="store_true")

    p_install_pair = sub.add_parser("install-pair")
    p_install_pair.add_argument("--source-language", required=True)
    p_install_pair.add_argument("--target-language", required=True)
    p_install_pair.add_argument("--models-dir", default=None)

    p_install_bundle = sub.add_parser("install-bundle")
    p_install_bundle.add_argument("--bundle", choices=["lightweight", "full"], default="lightweight")
    p_install_bundle.add_argument("--models-dir", default=None)
    p_install_bundle.add_argument("--stop-on-error", action="store_true")

    p_install_nllb_dep = sub.add_parser("install-nllb")
    p_install_nllb_dep.add_argument("--upgrade", action="store_true")
    p_install_nllb_dep.add_argument("--include-torch", action="store_true")

    p_nllb_matrix = sub.add_parser("nllb-matrix")
    p_nllb_matrix.add_argument("--bundle", choices=["lightweight", "full"], default="lightweight")
    p_nllb_matrix.add_argument("--models-dir", default="semantic/language/models")
    p_nllb_matrix.add_argument("--model", default=DEFAULT_NLLB_MODEL_ID)

    p_install_nllb_model = sub.add_parser("install-nllb-model")
    p_install_nllb_model.add_argument("--models-dir", default="semantic/language/models")
    p_install_nllb_model.add_argument("--model", default=DEFAULT_NLLB_MODEL_ID)
    p_install_nllb_model.add_argument("--force", action="store_true")

    p_install_nllb_bundle = sub.add_parser("install-nllb-bundle")
    p_install_nllb_bundle.add_argument("--bundle", choices=["lightweight", "full"], default="lightweight")
    p_install_nllb_bundle.add_argument("--models-dir", default="semantic/language/models")
    p_install_nllb_bundle.add_argument("--model", default=DEFAULT_NLLB_MODEL_ID)
    p_install_nllb_bundle.add_argument("--force", action="store_true")

    p_config = sub.add_parser("write-config")
    p_config.add_argument("--out", required=True)

    return ap


def main() -> None:
    args = build_arg_parser().parse_args()

    if args.command == "status":
        payload = {
            "argos_dependency": asdict(check_argos_dependency()),
            "argos_installed_pairs": [pair_dict(s, t) for s, t in get_installed_argos_pairs()],
            "nllb_dependencies": check_nllb_dependencies(),
            "nllb_lightweight": [asdict(x) for x in get_nllb_matrix(get_recommended_pairs("lightweight"))],
            "recommended_languages": [{"code": c, "name": LANGUAGE_NAMES.get(c, c)} for c in RECOMMENDED_LANGUAGE_CODES],
            "official_default_chain": ["static_dictionary", "argos", "nllb"],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if args.command == "matrix":
        print(json.dumps([asdict(x) for x in get_argos_package_matrix(get_recommended_pairs(args.bundle), update_index=bool(args.update_index))], ensure_ascii=False, indent=2))
        return
    if args.command == "install-argos":
        code = install_argos_dependency(upgrade=bool(args.upgrade))
        print(json.dumps({"return_code": code}, indent=2))
        raise SystemExit(code)
    if args.command == "install-pair":
        changed = install_argos_language_pair(args.source_language, args.target_language, install_dir=args.models_dir)
        print(json.dumps({"installed": bool(changed), **pair_dict(args.source_language, args.target_language)}, indent=2))
        return
    if args.command == "install-bundle":
        result = install_argos_language_bundle(get_recommended_pairs(args.bundle), install_dir=args.models_dir, stop_on_error=bool(args.stop_on_error))
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return
    if args.command == "install-nllb":
        code = install_nllb_dependencies(upgrade=bool(args.upgrade), include_torch=bool(args.include_torch))
        print(json.dumps({"return_code": code}, indent=2))
        raise SystemExit(code)
    if args.command == "nllb-matrix":
        print(json.dumps([asdict(x) for x in get_nllb_matrix(get_recommended_pairs(args.bundle), models_dir=args.models_dir, model_id=args.model)], ensure_ascii=False, indent=2))
        return
    if args.command == "install-nllb-model":
        changed = install_nllb_model(models_dir=args.models_dir, model_id=args.model, force=bool(args.force))
        print(json.dumps({"installed": bool(changed), "model_id": args.model, "local_path": str(nllb_local_dir(args.models_dir, args.model))}, ensure_ascii=False, indent=2))
        return
    if args.command == "install-nllb-bundle":
        result = install_nllb_bundle(get_recommended_pairs(args.bundle), models_dir=args.models_dir, model_id=args.model, force=bool(args.force))
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return
    if args.command == "write-config":
        print(json.dumps(write_provider_config_template(Path(args.out)), ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()

# -----------------------------
# UI-friendly Argos discovery helpers
# -----------------------------

def get_available_argos_language_pairs(*, update_index: bool = True) -> List[Tuple[str, str]]:
    """Return all language pairs currently advertised by the Argos package index."""
    pairs: List[Tuple[str, str]] = []
    for pkg in get_available_argos_packages(update_index=update_index):
        src = canonical_lang(_pkg_attr(pkg, "from_code", "source_code", "source_language", "from_lang"))
        tgt = canonical_lang(_pkg_attr(pkg, "to_code", "target_code", "target_language", "to_lang"))
        if src != "und" and tgt != "und" and src != tgt:
            pairs.append((src, tgt))
    return sorted(set(pairs))


def get_available_argos_languages(*, update_index: bool = True) -> List[str]:
    """Return unique language codes present in the Argos package index."""
    langs = set()
    for src, tgt in get_available_argos_language_pairs(update_index=update_index):
        langs.add(src)
        langs.add(tgt)
    return sorted(langs)
