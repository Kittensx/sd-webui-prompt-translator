from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from language.utils.language_utils import canonical_lang, normalize_query_text, stable_hash
except Exception:
    def canonical_lang(lang: str | None) -> str:
        return (lang or "und").strip().lower() or "und"
    def normalize_query_text(text: str) -> str:
        return " ".join((text or "").strip().lower().split())
    def stable_hash(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS search_result_cache (
  cache_key TEXT PRIMARY KEY,
  query TEXT NOT NULL,
  query_norm TEXT NOT NULL,
  query_language TEXT NOT NULL,
  canonical_language TEXT NOT NULL,
  provider TEXT NOT NULL,
  search_context_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  result_count INTEGER NOT NULL DEFAULT 0,
  byte_size INTEGER NOT NULL DEFAULT 0,
  hit_count INTEGER NOT NULL DEFAULT 0,
  miss_count INTEGER NOT NULL DEFAULT 0,
  pinned INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_accessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_search_result_cache_query_norm
  ON search_result_cache(query_norm, query_language, canonical_language);
CREATE INDEX IF NOT EXISTS idx_search_result_cache_access
  ON search_result_cache(pinned, last_accessed_at);
CREATE INDEX IF NOT EXISTS idx_search_result_cache_expires
  ON search_result_cache(expires_at);

CREATE TABLE IF NOT EXISTS search_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  query TEXT NOT NULL,
  query_norm TEXT NOT NULL,
  query_language TEXT NOT NULL,
  canonical_language TEXT NOT NULL,
  provider TEXT NOT NULL,
  cache_key TEXT,
  cache_hit INTEGER NOT NULL DEFAULT 0,
  result_count INTEGER NOT NULL DEFAULT 0,
  expanded_queries_json TEXT NOT NULL DEFAULT '[]',
  search_context_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_search_history_created
  ON search_history(created_at);
CREATE INDEX IF NOT EXISTS idx_search_history_query_norm
  ON search_history(query_norm);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_after_days(days: Optional[float]) -> Optional[str]:
    if days is None or days <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(days=float(days))).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


@dataclass
class SearchCachePolicy:
    enabled: bool = True
    ttl_days: Optional[float] = 30
    max_rows: Optional[int] = 5000
    max_bytes: Optional[int] = 50 * 1024 * 1024
    history_days: Optional[float] = 90
    history_max_rows: Optional[int] = 20000


@dataclass
class SearchCacheLookup:
    hit: bool
    cache_key: str
    payload: Optional[Dict[str, Any]] = None


class SearchResultCache:
    """
    SQLite cache for user-created searches.

    This cache stores only search payloads and search history. It does not copy
    pack JSON content. Cache identity is based on:
      query + detected/canonical language + provider + search context.

    The search context should include values that change result shape, such as:
      packs_root, catalog_fingerprint, preset, max_results, display_format,
      pack_search_engine version/path, and language index version if available.
    """

    def __init__(self, db_path: Path | str, *, policy: Optional[SearchCachePolicy] = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.policy = policy or SearchCachePolicy()
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def make_cache_key(
        self,
        *,
        query: str,
        query_language: str,
        canonical_language: str,
        provider: str,
        search_context: Dict[str, Any],
    ) -> str:
        identity = {
            "query_norm": normalize_query_text(query),
            "query_language": canonical_lang(query_language),
            "canonical_language": canonical_lang(canonical_language),
            "provider": provider or "unknown",
            "search_context": search_context or {},
        }
        return stable_hash(identity)

    def get(
        self,
        *,
        query: str,
        query_language: str = "und",
        canonical_language: str = "en",
        provider: str = "default",
        search_context: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        record_history: bool = True,
    ) -> SearchCacheLookup:
        if search_context is None:
            search_context = params or {}
        cache_key = self.make_cache_key(
            query=query,
            query_language=query_language,
            canonical_language=canonical_language,
            provider=provider,
            search_context=search_context,
        )
        if not self.policy.enabled:
            if record_history:
                self.record_history(
                    query=query,
                    query_language=query_language,
                    canonical_language=canonical_language,
                    provider=provider,
                    cache_key=cache_key,
                    cache_hit=False,
                    result_count=0,
                    expanded_queries=[],
                    search_context=search_context,
                )
            return SearchCacheLookup(hit=False, cache_key=cache_key)

        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT result_json, result_count, expires_at FROM search_result_cache
                WHERE cache_key=?
                LIMIT 1
                """,
                (cache_key,),
            ).fetchone()
            if not row:
                conn.execute(
                    "UPDATE search_result_cache SET miss_count=miss_count+1 WHERE cache_key=?",
                    (cache_key,),
                )
                conn.commit()
                if record_history:
                    self.record_history(
                        query=query,
                        query_language=query_language,
                        canonical_language=canonical_language,
                        provider=provider,
                        cache_key=cache_key,
                        cache_hit=False,
                        result_count=0,
                        expanded_queries=[],
                        search_context=search_context,
                    )
                return SearchCacheLookup(hit=False, cache_key=cache_key)

            expires_at = row["expires_at"]
            if expires_at and expires_at <= utc_now():
                conn.execute("DELETE FROM search_result_cache WHERE cache_key=? AND pinned=0", (cache_key,))
                conn.commit()
                if record_history:
                    self.record_history(
                        query=query,
                        query_language=query_language,
                        canonical_language=canonical_language,
                        provider=provider,
                        cache_key=cache_key,
                        cache_hit=False,
                        result_count=0,
                        expanded_queries=[],
                        search_context=search_context,
                    )
                return SearchCacheLookup(hit=False, cache_key=cache_key)

            try:
                payload = json.loads(row["result_json"])
            except Exception:
                payload = None
            if not isinstance(payload, dict):
                conn.execute("DELETE FROM search_result_cache WHERE cache_key=? AND pinned=0", (cache_key,))
                conn.commit()
                return SearchCacheLookup(hit=False, cache_key=cache_key)

            conn.execute(
                """
                UPDATE search_result_cache
                SET hit_count=hit_count+1, last_accessed_at=CURRENT_TIMESTAMP
                WHERE cache_key=?
                """,
                (cache_key,),
            )
            conn.commit()

        if record_history:
            self.record_history(
                query=query,
                query_language=query_language,
                canonical_language=canonical_language,
                provider=provider,
                cache_key=cache_key,
                cache_hit=True,
                result_count=int(row["result_count"]),
                expanded_queries=payload.get("expanded_queries", []),
                search_context=search_context,
            )
        payload["search_cache"] = {"hit": True, "cache_key": cache_key}
        return SearchCacheLookup(hit=True, cache_key=cache_key, payload=payload)

    def set(
        self,
        *,
        query: str,
        query_language: str = "und",
        canonical_language: str = "en",
        provider: str = "default",
        search_context: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        ttl_days: Optional[float] = None,
        ttl_seconds: Optional[float] = None,
        pinned: bool = False,
    ) -> str:
        if search_context is None:
            search_context = params or {}
        if payload is None:
            payload = {}
        if ttl_seconds is not None and ttl_days is None:
            ttl_days = float(ttl_seconds) / 86400.0
        result_json = _json_dumps(payload)
        result_count = len(payload.get("results") or []) if isinstance(payload, dict) else 0
        expires = utc_after_days(self.policy.ttl_days if ttl_days is None else ttl_days)
        cache_key = self.make_cache_key(
            query=query,
            query_language=query_language,
            canonical_language=canonical_language,
            provider=provider,
            search_context=search_context,
        )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO search_result_cache(
                  cache_key, query, query_norm, query_language, canonical_language,
                  provider, search_context_json, result_json, result_count, byte_size,
                  hit_count, miss_count, pinned, created_at, updated_at, last_accessed_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          COALESCE((SELECT hit_count FROM search_result_cache WHERE cache_key=?), 0),
                          COALESCE((SELECT miss_count FROM search_result_cache WHERE cache_key=?), 0),
                          ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
                """,
                (
                    cache_key,
                    query,
                    normalize_query_text(query),
                    canonical_lang(query_language),
                    canonical_lang(canonical_language),
                    provider or "unknown",
                    _json_dumps(search_context or {}),
                    result_json,
                    int(result_count),
                    len(result_json.encode("utf-8")),
                    cache_key,
                    cache_key,
                    1 if pinned else 0,
                    expires,
                ),
            )
            conn.commit()
        self.enforce_limits()
        return cache_key

    def record_history(
        self,
        *,
        query: str,
        query_language: str,
        canonical_language: str,
        provider: str,
        cache_key: Optional[str],
        cache_hit: bool,
        result_count: int,
        expanded_queries: Sequence[str],
        search_context: Dict[str, Any],
    ) -> None:
       
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO search_history(
                  query, query_norm, query_language, canonical_language, provider,
                  cache_key, cache_hit, result_count, expanded_queries_json,
                  search_context_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    query,
                    normalize_query_text(query),
                    canonical_lang(query_language),
                    canonical_lang(canonical_language),
                    provider or "unknown",
                    cache_key,
                    1 if cache_hit else 0,
                    int(result_count or 0),
                    json.dumps(list(expanded_queries or []), ensure_ascii=False),
                    _json_dumps(search_context or {}),
                ),
            )
            conn.commit()
        self.enforce_history_limits()

    def stats(self) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS rows, COALESCE(SUM(byte_size),0) AS bytes,
                       COALESCE(SUM(hit_count),0) AS hits,
                       COALESCE(SUM(miss_count),0) AS misses,
                       COALESCE(SUM(pinned),0) AS pinned
                FROM search_result_cache
                """
            ).fetchone()
            history_rows = conn.execute("SELECT COUNT(*) FROM search_history").fetchone()[0]
            expired_rows = conn.execute(
                "SELECT COUNT(*) FROM search_result_cache WHERE expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP AND pinned=0"
            ).fetchone()[0]
        return {
            "cache_rows": int(row["rows"]),
            "cache_bytes": int(row["bytes"]),
            "cache_hits": int(row["hits"]),
            "cache_misses": int(row["misses"]),
            "pinned_rows": int(row["pinned"]),
            "expired_rows": int(expired_rows),
            "history_rows": int(history_rows),
            "db_path": str(self.db_path),
        }

    def list_recent(self, *, limit: int = 25, history: bool = False) -> List[Dict[str, Any]]:
        table = "search_history" if history else "search_result_cache"
        if history:
            sql = """
            SELECT id, query, query_language, canonical_language, provider, cache_hit,
                   result_count, created_at
            FROM search_history ORDER BY created_at DESC LIMIT ?
            """
        else:
            sql = """
            SELECT cache_key, query, query_language, canonical_language, provider,
                   result_count, byte_size, hit_count, pinned, updated_at, last_accessed_at, expires_at
            FROM search_result_cache ORDER BY last_accessed_at DESC LIMIT ?
            """
        with self.connect() as conn:
            rows = conn.execute(sql, (max(1, int(limit)),)).fetchall()
        return [dict(r) for r in rows]

    def clear_all(self, *, include_history: bool = True, include_pinned: bool = False) -> int:
        with self.connect() as conn:
            if include_pinned:
                cur = conn.execute("DELETE FROM search_result_cache")
            else:
                cur = conn.execute("DELETE FROM search_result_cache WHERE pinned=0")
            count = cur.rowcount or 0
            if include_history:
                cur2 = conn.execute("DELETE FROM search_history")
                count += cur2.rowcount or 0
            conn.commit()
        return int(count)

    def clear_history(self) -> int:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM search_history")
            conn.commit()
            return int(cur.rowcount or 0)

    def purge_expired(self) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM search_result_cache WHERE expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP AND pinned=0"
            )
            conn.commit()
            return int(cur.rowcount or 0)

    def purge_older_than(self, *, days: Optional[float] = None, before: Optional[str] = None, include_history: bool = False) -> int:
        if before:
            cutoff = before
        elif days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=float(days))).isoformat(timespec="seconds").replace("+00:00", "Z")
        else:
            raise ValueError("Provide days or before")
        count = 0
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM search_result_cache WHERE last_accessed_at < ? AND pinned=0",
                (cutoff,),
            )
            count += cur.rowcount or 0
            if include_history:
                cur2 = conn.execute("DELETE FROM search_history WHERE created_at < ?", (cutoff,))
                count += cur2.rowcount or 0
            conn.commit()
        return int(count)

    def enforce_limits(self, *, max_rows: Optional[int] = None, max_bytes: Optional[int] = None) -> int:
        max_rows = self.policy.max_rows if max_rows is None else max_rows
        max_bytes = self.policy.max_bytes if max_bytes is None else max_bytes
        deleted = 0
        with self.connect() as conn:
            if max_rows is not None and max_rows > 0:
                rows = conn.execute(
                    """
                    SELECT cache_key FROM search_result_cache
                    WHERE pinned=0
                    ORDER BY last_accessed_at ASC
                    LIMIT (
                      SELECT MAX(COUNT(*) - ?, 0) FROM search_result_cache WHERE pinned=0
                    )
                    """,
                    (int(max_rows),),
                ).fetchall()
                keys = [r["cache_key"] for r in rows]
                if keys:
                    deleted += self._delete_keys(conn, keys)
            if max_bytes is not None and max_bytes > 0:
                total = conn.execute("SELECT COALESCE(SUM(byte_size),0) FROM search_result_cache").fetchone()[0]
                while total and total > int(max_bytes):
                    row = conn.execute(
                        """
                        SELECT cache_key, byte_size FROM search_result_cache
                        WHERE pinned=0
                        ORDER BY last_accessed_at ASC
                        LIMIT 1
                        """
                    ).fetchone()
                    if not row:
                        break
                    conn.execute("DELETE FROM search_result_cache WHERE cache_key=?", (row["cache_key"],))
                    deleted += 1
                    total -= int(row["byte_size"] or 0)
            conn.commit()
        return int(deleted)

    def enforce_history_limits(self, *, max_rows: Optional[int] = None, days: Optional[float] = None) -> int:
        max_rows = self.policy.history_max_rows if max_rows is None else max_rows
        days = self.policy.history_days if days is None else days
        deleted = 0
        with self.connect() as conn:
            if days is not None and days > 0:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=float(days))).isoformat(timespec="seconds").replace("+00:00", "Z")
                cur = conn.execute("DELETE FROM search_history WHERE created_at < ?", (cutoff,))
                deleted += cur.rowcount or 0
            if max_rows is not None and max_rows > 0:
                rows = conn.execute(
                    """
                    SELECT id FROM search_history
                    ORDER BY created_at ASC
                    LIMIT (
                      SELECT MAX(COUNT(*) - ?, 0) FROM search_history
                    )
                    """,
                    (int(max_rows),),
                ).fetchall()
                ids = [int(r["id"]) for r in rows]
                if ids:
                    placeholders = ",".join("?" for _ in ids)
                    cur = conn.execute(f"DELETE FROM search_history WHERE id IN ({placeholders})", ids)
                    deleted += cur.rowcount or 0
            conn.commit()
        return int(deleted)

    def pin(self, cache_key: str, pinned: bool = True) -> int:
        with self.connect() as conn:
            cur = conn.execute("UPDATE search_result_cache SET pinned=? WHERE cache_key=?", (1 if pinned else 0, cache_key))
            conn.commit()
            return int(cur.rowcount or 0)

    def delete_key(self, cache_key: str) -> int:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM search_result_cache WHERE cache_key=? AND pinned=0", (cache_key,))
            conn.commit()
            return int(cur.rowcount or 0)

    def _delete_keys(self, conn: sqlite3.Connection, keys: Sequence[str]) -> int:
        if not keys:
            return 0
        placeholders = ",".join("?" for _ in keys)
        cur = conn.execute(f"DELETE FROM search_result_cache WHERE cache_key IN ({placeholders}) AND pinned=0", list(keys))
        return int(cur.rowcount or 0)


def make_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Manage Semantic Prompt user search cache.")
    ap.add_argument("--db", required=True, type=Path, help="Search cache SQLite DB path")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("stats")

    p_list = sub.add_parser("list")
    p_list.add_argument("--limit", type=int, default=25)
    p_list.add_argument("--history", action="store_true")

    p_clear = sub.add_parser("clear")
    p_clear.add_argument("--include-history", action="store_true")
    p_clear.add_argument("--include-pinned", action="store_true")

    sub.add_parser("clear-history")
    sub.add_parser("purge-expired")

    p_old = sub.add_parser("purge-older-than")
    p_old.add_argument("--days", type=float)
    p_old.add_argument("--before")
    p_old.add_argument("--include-history", action="store_true")

    p_limits = sub.add_parser("enforce-limits")
    p_limits.add_argument("--max-rows", type=int)
    p_limits.add_argument("--max-bytes", type=int)

    p_pin = sub.add_parser("pin")
    p_pin.add_argument("cache_key")
    p_pin.add_argument("--unpin", action="store_true")

    p_delete = sub.add_parser("delete")
    p_delete.add_argument("cache_key")
    return ap


def main() -> None:
    args = make_parser().parse_args()
    cache = SearchResultCache(args.db)

    if args.command == "stats":
        print(_json_pretty(cache.stats()))
    elif args.command == "list":
        print(_json_pretty(cache.list_recent(limit=args.limit, history=args.history)))
    elif args.command == "clear":
        print(_json_pretty({"deleted": cache.clear_all(include_history=args.include_history, include_pinned=args.include_pinned)}))
    elif args.command == "clear-history":
        print(_json_pretty({"deleted": cache.clear_history()}))
    elif args.command == "purge-expired":
        print(_json_pretty({"deleted": cache.purge_expired()}))
    elif args.command == "purge-older-than":
        print(_json_pretty({"deleted": cache.purge_older_than(days=args.days, before=args.before, include_history=args.include_history)}))
    elif args.command == "enforce-limits":
        print(_json_pretty({"deleted": cache.enforce_limits(max_rows=args.max_rows, max_bytes=args.max_bytes)}))
    elif args.command == "pin":
        print(_json_pretty({"updated": cache.pin(args.cache_key, pinned=not args.unpin)}))
    elif args.command == "delete":
        print(_json_pretty({"deleted": cache.delete_key(args.cache_key)}))

SearchCache = SearchResultCache

if __name__ == "__main__":
    main()
