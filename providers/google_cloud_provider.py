from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import List

from language_utils import canonical_lang


@dataclass
class Provider:
    """
    Optional Google Cloud Translation API provider scaffold.

    Env vars:
      GOOGLE_TRANSLATE_API_KEY=...

    No request is made unless explicitly selected.
    """
    name: str = "google_cloud"
    api_key: str | None = None
    api_url: str = "https://translation.googleapis.com/language/translate/v2"
    timeout: int = 30
    fallback_to_original: bool = True

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.getenv("GOOGLE_TRANSLATE_API_KEY")

    def translate_texts(self, texts: List[str], *, source_language: str, target_language: str) -> List[str]:
        if not self.api_key:
            if self.fallback_to_original:
                return list(texts)
            raise RuntimeError("GOOGLE_TRANSLATE_API_KEY is not set")
        src = canonical_lang(source_language)
        tgt = canonical_lang(target_language)
        url = f"{self.api_url}?key={self.api_key}"
        payload = {"q": texts, "target": tgt, "format": "text"}
        if src != "und":
            payload["source"] = src
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            translations = (((data.get("data") or {}).get("translations")) or [])
            out = []
            for i, original in enumerate(texts):
                if i < len(translations) and isinstance(translations[i], dict):
                    out.append(str(translations[i].get("translatedText") or original))
                else:
                    out.append(original)
            return out
        except Exception:
            if self.fallback_to_original:
                return list(texts)
            raise
