from __future__ import annotations

import argparse
import json
from pathlib import Path

from language.translation.translation_cache import TranslationCache


def main() -> None:
    ap = argparse.ArgumentParser(description="Inspect Semantic Prompt translation cache.")
    ap.add_argument("--cache-db", required=True, type=Path)
    args = ap.parse_args()
    cache = TranslationCache(args.cache_db)
    print(json.dumps(cache.stats(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
