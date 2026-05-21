from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import List

from language_utils import canonical_lang

DEEPL_LANG_MAP = {
    "en": "EN",
    "ja": "JA",
    "es": "ES",
    "fr": "FR",
    "de": "DE",
    "it": "IT",
    "pt": "PT",
    "zh": "ZH",
    "ko": "KO",
}


@dataclass
class Provider:
    """
    Optional DeepL API provider.

    Env vars:
      DEEPL_API_KEY=...
      DEEPL_API_URL=https://api-free.deepl.com/v2/translate

    No request is made unless this provider is explicitly selected.
    """
    name: str = "deepl"
    api_key: str | None = None
    api_url: str | None = None
    timeout: int = 30
    fallback_to_original: bool = True

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.getenv("DEEPL_API_KEY")
        self.api_url = self.api_url or os.getenv("DEEPL_API_URL") or "https://api-free.deepl.com/v2/translate"

    def translate_texts(self, texts: List[str], *, source_language: str, target_language: str) -> List[str]:
        if not self.api_key:
            if self.fallback_to_original:
                return list(texts)
            raise RuntimeError("DEEPL_API_KEY is not set")

        src = DEEPL_LANG_MAP.get(canonical_lang(source_language).split("-")[0].lower())
        tgt = DEEPL_LANG_MAP.get(canonical_lang(target_language).split("-")[0].lower())
        if not tgt:
            if self.fallback_to_original:
                return list(texts)
            raise RuntimeError(f"Unsupported DeepL target language: {target_language}")

        data = []
        for t in texts:
            data.append(("text", t))
        data.append(("target_lang", tgt))
        if src:
            data.append(("source_lang", src))
        body = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(
            self.api_url,
            data=body,
            headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            translations = payload.get("translations") or []
            out = []
            for i, original in enumerate(texts):
                if i < len(translations) and isinstance(translations[i], dict):
                    out.append(str(translations[i].get("text") or original))
                else:
                    out.append(original)
            return out
        except Exception:
            if self.fallback_to_original:
                return list(texts)
            raise
