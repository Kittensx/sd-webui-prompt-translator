from __future__ import annotations

"""
Optional downloadable dictionary manager for Prompt Translator.

This module intentionally does not ship large dictionaries. It provides:
- a local installed dictionary folder
- import/download helpers
- normalization into the JSON record format used by StaticDictionaryTranslationProvider
- simple status/listing for the A1111 UI

Supported input formats:
1) JSON record list:
   [{"source_language":"en", "target_language":"ja", "source":"duck", "target":"アヒル"}]
2) nested JSON:
   {"en": {"ja": {"duck": "アヒル"}}}
3) flat JSON pair map, when source/target are provided:
   {"duck": "アヒル"}
4) TSV/TXT lines:
   duck\tアヒル
   duck = アヒル
   duck,アヒル
"""

import json
import re
import shutil
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:
    from language_utils import canonical_lang, stable_hash
except Exception:
    from .language_utils import canonical_lang, stable_hash


@dataclass
class DictionaryRecord:
    source_language: str
    target_language: str
    source: str
    target: str
    provider: str = "local"
    source_name: str = "manual"

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class DictionaryInfo:
    path: str
    name: str
    source_language: str
    target_language: str
    provider: str
    record_count: int
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def installed_dictionaries_dir(extension_root: str | Path) -> Path:
    return Path(extension_root).resolve() / "language" / "dictionaries" / "installed"


def dictionary_manifest_path(extension_root: str | Path) -> Path:
    return Path(extension_root).resolve() / "language" / "dictionaries" / "dictionary_manifest.json"


def _safe_name(value: str) -> str:
    value = (value or "dictionary").strip().lower()
    value = re.sub(r"[^a-z0-9_.-]+", "_", value)
    return value.strip("._-") or "dictionary"


def _clean_pair_text(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def _dedupe_records(records: Iterable[DictionaryRecord]) -> List[DictionaryRecord]:
    out: List[DictionaryRecord] = []
    seen = set()
    for rec in records:
        src = canonical_lang(rec.source_language)
        tgt = canonical_lang(rec.target_language)
        source = _clean_pair_text(rec.source)
        target = _clean_pair_text(rec.target)
        if not source or not target or src == "und" or tgt == "und":
            continue
        key = (src, tgt, source.casefold(), target.casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append(DictionaryRecord(src, tgt, source, target, rec.provider, rec.source_name))
    return out


def parse_dictionary_data(
    data: Any,
    *,
    source_language: str = "",
    target_language: str = "",
    provider: str = "local",
    source_name: str = "manual",
) -> List[DictionaryRecord]:
    records: List[DictionaryRecord] = []
    default_src = canonical_lang(source_language)
    default_tgt = canonical_lang(target_language)

    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            src = canonical_lang(str(item.get("source_language") or item.get("src") or default_src))
            tgt = canonical_lang(str(item.get("target_language") or item.get("tgt") or default_tgt))
            source = _clean_pair_text(item.get("source") or item.get("src_text") or item.get("term") or item.get("headword"))
            target = _clean_pair_text(item.get("target") or item.get("translation") or item.get("definition") or item.get("gloss"))
            records.append(DictionaryRecord(src, tgt, source, target, provider, source_name))
        return _dedupe_records(records)

    if isinstance(data, dict):
        nested_used = False
        for src, tgt_map in data.items():
            if not isinstance(tgt_map, dict):
                continue
            for tgt, pair_map in tgt_map.items():
                if not isinstance(pair_map, dict):
                    continue
                nested_used = True
                for source, target in pair_map.items():
                    records.append(DictionaryRecord(canonical_lang(str(src)), canonical_lang(str(tgt)), _clean_pair_text(source), _clean_pair_text(target), provider, source_name))
        if nested_used:
            return _dedupe_records(records)

        # Flat map requires explicit source/target language.
        if default_src != "und" and default_tgt != "und":
            for source, target in data.items():
                records.append(DictionaryRecord(default_src, default_tgt, _clean_pair_text(source), _clean_pair_text(target), provider, source_name))
            return _dedupe_records(records)

    return []


def parse_dictionary_text(
    text: str,
    *,
    source_language: str,
    target_language: str,
    provider: str = "local",
    source_name: str = "manual",
) -> List[DictionaryRecord]:
    src = canonical_lang(source_language)
    tgt = canonical_lang(target_language)
    records: List[DictionaryRecord] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            left, right = line.split("\t", 1)
        elif " = " in line:
            left, right = line.split(" = ", 1)
        elif "," in line:
            left, right = line.split(",", 1)
        else:
            continue
        records.append(DictionaryRecord(src, tgt, left.strip(), right.strip(), provider, source_name))
    return _dedupe_records(records)


def read_dictionary_file(path: str | Path, *, source_language: str = "", target_language: str = "", provider: str = "local") -> List[DictionaryRecord]:
    path = Path(path)
    suffix = path.suffix.lower()
    source_name = path.stem
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return parse_dictionary_data(data, source_language=source_language, target_language=target_language, provider=provider, source_name=source_name)
    return parse_dictionary_text(path.read_text(encoding="utf-8"), source_language=source_language, target_language=target_language, provider=provider, source_name=source_name)


def write_installed_dictionary(
    extension_root: str | Path,
    records: Sequence[DictionaryRecord],
    *,
    name: str,
    source_language: str,
    target_language: str,
    provider: str = "local",
) -> DictionaryInfo:
    root = installed_dictionaries_dir(extension_root)
    root.mkdir(parents=True, exist_ok=True)
    src = canonical_lang(source_language)
    tgt = canonical_lang(target_language)
    clean_name = _safe_name(name)
    filename = f"{src}_{tgt}.{clean_name}.json"
    dest = root / filename
    cleaned = _dedupe_records(records)
    payload = [r.to_dict() for r in cleaned if canonical_lang(r.source_language) == src and canonical_lang(r.target_language) == tgt]
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    info = DictionaryInfo(str(dest), clean_name, src, tgt, provider, len(payload), True)
    update_manifest(extension_root)
    return info


def import_dictionary_file(
    extension_root: str | Path,
    file_path: str | Path,
    *,
    source_language: str,
    target_language: str,
    name: str = "",
    provider: str = "local_import",
) -> DictionaryInfo:
    path = Path(file_path).expanduser().resolve()
    records = read_dictionary_file(path, source_language=source_language, target_language=target_language, provider=provider)
    return write_installed_dictionary(
        extension_root,
        records,
        name=name or path.stem,
        source_language=source_language,
        target_language=target_language,
        provider=provider,
    )


def download_dictionary_url(
    extension_root: str | Path,
    url: str,
    *,
    source_language: str,
    target_language: str,
    name: str = "downloaded",
    provider: str = "url_download",
    timeout: int = 60,
) -> DictionaryInfo:
    url = (url or "").strip()
    if not url:
        raise ValueError("Dictionary URL is empty")
    tmp_root = Path(extension_root).resolve() / "language" / "dictionaries" / "downloads"
    tmp_root.mkdir(parents=True, exist_ok=True)
    suffix = ".json" if url.lower().split("?", 1)[0].endswith(".json") else ".txt"
    tmp = tmp_root / f"{_safe_name(name)}_{stable_hash(url)[:10]}{suffix}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        data = response.read()
    tmp.write_bytes(data)
    return import_dictionary_file(
        extension_root,
        tmp,
        source_language=source_language,
        target_language=target_language,
        name=name,
        provider=provider,
    )


def list_installed_dictionaries(extension_root: str | Path) -> List[DictionaryInfo]:
    root = installed_dictionaries_dir(extension_root)
    root.mkdir(parents=True, exist_ok=True)
    infos: List[DictionaryInfo] = []
    for path in sorted(root.glob("*.json")):
        try:
            records = read_dictionary_file(path)
        except Exception:
            records = []
        src = tgt = "und"
        provider = "local"
        if records:
            src = canonical_lang(records[0].source_language)
            tgt = canonical_lang(records[0].target_language)
            provider = records[0].provider
        else:
            m = re.match(r"([a-z]{2,3})_([a-z]{2,3})\.", path.name)
            if m:
                src, tgt = canonical_lang(m.group(1)), canonical_lang(m.group(2))
        infos.append(DictionaryInfo(str(path), path.stem, src, tgt, provider, len(records), True))
    return infos


def dictionary_paths(extension_root: str | Path, *, source_language: str = "", target_language: str = "") -> List[Path]:
    src = canonical_lang(source_language) if source_language else ""
    tgt = canonical_lang(target_language) if target_language else ""
    paths: List[Path] = []
    for info in list_installed_dictionaries(extension_root):
        if src and info.source_language != src:
            continue
        if tgt and info.target_language != tgt:
            continue
        paths.append(Path(info.path))
    return paths


def update_manifest(extension_root: str | Path) -> Dict[str, Any]:
    infos = [info.to_dict() for info in list_installed_dictionaries(extension_root)]
    manifest = {
        "version": 1,
        "installed_count": len(infos),
        "dictionaries": infos,
    }
    path = dictionary_manifest_path(extension_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def write_source_template(extension_root: str | Path) -> Path:
    path = Path(extension_root).resolve() / "language" / "dictionaries" / "dictionary_sources.example.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "notes": [
            "Large dictionaries are not bundled. Add direct downloadable JSON/TSV dictionary URLs here or use the UI URL installer.",
            "Supported downloaded file formats: JSON records, nested JSON, flat JSON with source/target selected, TSV/TXT source-target lines.",
            "Potential sources to evaluate manually: WikDict, FreeDict, JMdict-derived exports, Wiktionary-derived exports. Check licenses before redistribution.",
        ],
        "sources": []
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Manage local Prompt Translator dictionaries")
    ap.add_argument("--extension-root", default=str(Path(__file__).resolve().parents[1]))
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    p_import = sub.add_parser("import")
    p_import.add_argument("file")
    p_import.add_argument("--source", required=True)
    p_import.add_argument("--target", required=True)
    p_import.add_argument("--name", default="")
    p_url = sub.add_parser("download-url")
    p_url.add_argument("url")
    p_url.add_argument("--source", required=True)
    p_url.add_argument("--target", required=True)
    p_url.add_argument("--name", default="downloaded")
    sub.add_parser("write-template")
    args = ap.parse_args()
    if args.command == "status":
        print(json.dumps(update_manifest(args.extension_root), ensure_ascii=False, indent=2))
    elif args.command == "import":
        print(json.dumps(import_dictionary_file(args.extension_root, args.file, source_language=args.source, target_language=args.target, name=args.name).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "download-url":
        print(json.dumps(download_dictionary_url(args.extension_root, args.url, source_language=args.source, target_language=args.target, name=args.name).to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "write-template":
        print(write_source_template(args.extension_root))
