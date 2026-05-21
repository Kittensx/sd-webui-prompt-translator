from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import argparse
import json
from language.translation.translation_providers import available_providers, get_provider


def main() -> None:
    ap = argparse.ArgumentParser(description="Smoke-test a Semantic Pack translation provider.")
    ap.add_argument("--provider", default="debug")
    ap.add_argument("--source-language", default="en")
    ap.add_argument("--target-language", default="ja")
    ap.add_argument("--text", action="append", default=["riverbank", "cherry blossoms"])
    ap.add_argument("--list", action="store_true", help="List known provider names")
    args = ap.parse_args()
    if args.list:
        print(json.dumps(available_providers(), indent=2))
        return
    provider = get_provider(args.provider)
    result = provider.translate_texts(args.text, source_language=args.source_language, target_language=args.target_language)
    print(json.dumps({"provider": getattr(provider, "name", args.provider), "result": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
