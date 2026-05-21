from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from language.utils.language_utils import canonical_lang, stable_hash


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS translation_cache (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pack_path TEXT NOT NULL,
  category TEXT NOT NULL,
  entry_key TEXT NOT NULL,
  field_name TEXT NOT NULL,
  source_language TEXT NOT NULL,
  target_language TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  translated_json TEXT NOT NULL,
  provider TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(pack_path, entry_key, field_name, source_language, target_language, source_hash)
);
CREATE INDEX IF NOT EXISTS idx_translation_cache_lookup
  ON translation_cache(pack_path, entry_key, field_name, target_language);
CREATE INDEX IF NOT EXISTS idx_translation_cache_category
  ON translation_cache(category, target_language);

CREATE TABLE IF NOT EXISTS pack_language_meta (
  pack_path TEXT PRIMARY KEY,
  category TEXT NOT NULL,
  source_language TEXT NOT NULL,
  detected_languages_json TEXT NOT NULL,
  language_confidence_json TEXT NOT NULL,
  supported_languages_json TEXT NOT NULL,
  key_count INTEGER NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS query_translation_cache (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  query TEXT NOT NULL,
  source_language TEXT NOT NULL,
  target_language TEXT NOT NULL,
  translated_json TEXT NOT NULL,
  provider TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(query, source_language, target_language, provider)
);
"""


@dataclass
class CacheKey:
    pack_path: str
    category: str
    entry_key: str
    field_name: str
    source_language: str
    target_language: str
    source_hash: str


class TranslationCache:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def source_hash(self, values: Sequence[str]) -> str:
        return stable_hash(list(values))

    #compatibility bridge
    def set_cached_translation(
        self,
        *,
        pack_path: str,
        category: str,
        entry_key: str,
        field_name: str,
        source_language: str,
        target_language: str,
        source_values,
        translated_values,
        provider="manual",
        model=None,
        metadata=None,
        **kwargs,
    ):
        return self.set_translation(
            pack_path=pack_path,
            category=category,
            entry_key=entry_key,
            field_name=field_name,
            source_language=source_language,
            target_language=target_language,
            source_values=source_values,
            translated_values=translated_values,
            provider=provider,
        )

    #for compatibility
    def get_cached_translation(
        self,
        *,
        pack_path: str,
        entry_key: str,
        field_name: str,
        source_language: str,
        target_language: str,
        source_values,
        **kwargs,
    ):
        return self.get_translation(
            pack_path=pack_path,
            entry_key=entry_key,
            field_name=field_name,
            source_language=source_language,
            target_language=target_language,
            source_values=source_values,
        )
        
    def get_translation(
        self,
        *,
        pack_path: str,
        entry_key: str,
        field_name: str,
        source_language: str,
        target_language: str,
        source_values: Sequence[str],
    ) -> Optional[List[str]]:
        src = canonical_lang(source_language)
        tgt = canonical_lang(target_language)
        h = self.source_hash(source_values)
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT translated_json FROM translation_cache
                WHERE pack_path=? AND entry_key=? AND field_name=?
                  AND source_language=? AND target_language=? AND source_hash=?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (pack_path, entry_key, field_name, src, tgt, h),
            ).fetchone()
        if not row:
            return None
        try:
            values = json.loads(row["translated_json"])
            return values if isinstance(values, list) else None
        except Exception:
            return None

    def set_translation(
        self,
        *,
        pack_path: str,
        category: str,
        entry_key: str,
        field_name: str,
        source_language: str,
        target_language: str,
        source_values: Sequence[str],
        translated_values: Sequence[str],
        provider: str,
    ) -> None:
        src = canonical_lang(source_language)
        tgt = canonical_lang(target_language)
        h = self.source_hash(source_values)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO translation_cache(
                  pack_path, category, entry_key, field_name, source_language,
                  target_language, source_hash, translated_json, provider, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    pack_path,
                    category,
                    entry_key,
                    field_name,
                    src,
                    tgt,
                    h,
                    json.dumps(list(translated_values), ensure_ascii=False),
                    provider,
                ),
            )
            conn.commit()

    def get_or_create_translation(
        self,
        *,
        pack_path: str,
        category: str,
        entry_key: str,
        field_name: str,
        source_language: str,
        target_language: str,
        source_values: Sequence[str],
        provider_obj: Any,
    ) -> List[str]:
        cached = self.get_translation(
            pack_path=pack_path,
            entry_key=entry_key,
            field_name=field_name,
            source_language=source_language,
            target_language=target_language,
            source_values=source_values,
        )
        if cached is not None:
            return cached
        translated = provider_obj.translate_texts(
            list(source_values),
            source_language=source_language,
            target_language=target_language,
        )
        self.set_translation(
            pack_path=pack_path,
            category=category,
            entry_key=entry_key,
            field_name=field_name,
            source_language=source_language,
            target_language=target_language,
            source_values=source_values,
            translated_values=translated,
            provider=getattr(provider_obj, "name", "unknown"),
        )
        return list(translated)

    def set_pack_language_meta(
        self,
        *,
        pack_path: str,
        category: str,
        source_language: str,
        detected_languages: Sequence[str],
        language_confidence: Dict[str, float],
        supported_languages: Sequence[str],
        key_count: int,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO pack_language_meta(
                  pack_path, category, source_language, detected_languages_json,
                  language_confidence_json, supported_languages_json, key_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    pack_path,
                    category,
                    canonical_lang(source_language),
                    json.dumps(list(detected_languages), ensure_ascii=False),
                    json.dumps(language_confidence, ensure_ascii=False, sort_keys=True),
                    json.dumps(list(supported_languages), ensure_ascii=False),
                    int(key_count),
                ),
            )
            conn.commit()

    def get_or_create_query_translation(
        self,
        query: str,
        *,
        source_language: str,
        target_language: str,
        provider_obj: Any,
    ) -> List[str]:
        src = canonical_lang(source_language)
        tgt = canonical_lang(target_language)
        provider = getattr(provider_obj, "name", "unknown")
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT translated_json FROM query_translation_cache
                WHERE query=? AND source_language=? AND target_language=? AND provider=?
                LIMIT 1
                """,
                (query, src, tgt, provider),
            ).fetchone()
            if row:
                try:
                    values = json.loads(row["translated_json"])
                    if isinstance(values, list):
                        return values
                except Exception:
                    pass
            translated = provider_obj.translate_texts([query], source_language=src, target_language=tgt)
            values = list(dict.fromkeys([query] + translated))
            conn.execute(
                """
                INSERT OR REPLACE INTO query_translation_cache(
                  query, source_language, target_language, translated_json, provider, updated_at
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (query, src, tgt, json.dumps(values, ensure_ascii=False), provider),
            )
            conn.commit()
            return values

    def stats(self) -> Dict[str, int]:
        with self.connect() as conn:
            return {
                "translation_rows": conn.execute("SELECT COUNT(*) FROM translation_cache").fetchone()[0],
                "pack_language_rows": conn.execute("SELECT COUNT(*) FROM pack_language_meta").fetchone()[0],
                "query_translation_rows": conn.execute("SELECT COUNT(*) FROM query_translation_cache").fetchone()[0],
            }
