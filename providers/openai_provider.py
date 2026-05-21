from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import List


@dataclass
class Provider:
    """
    Optional OpenAI API provider scaffold.

    Env vars:
      OPENAI_API_KEY=...
      OPENAI_TRANSLATION_MODEL=gpt-4.1-mini  (or another model chosen by user)

    This uses the Responses API shape loosely and is intentionally isolated as a plugin.
    Verify API details against your installed OpenAI SDK/docs before production use.
    """
    name: str = "openai"
    api_key: str | None = None
    model: str | None = None
    api_url: str = "https://api.openai.com/v1/responses"
    timeout: int = 60
    fallback_to_original: bool = True

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.getenv("OPENAI_API_KEY")
        self.model = self.model or os.getenv("OPENAI_TRANSLATION_MODEL") or "gpt-4.1-mini"

    def translate_texts(self, texts: List[str], *, source_language: str, target_language: str) -> List[str]:
        if not self.api_key:
            if self.fallback_to_original:
                return list(texts)
            raise RuntimeError("OPENAI_API_KEY is not set")

        prompt = (
            "Translate each string from {src} to {tgt}. Return ONLY a JSON array of strings, "
            "same order and same length. Preserve Stable Diffusion prompt usefulness; do not explain.\n\n"
            "Strings:\n{items}"
        ).format(src=source_language, tgt=target_language, items=json.dumps(texts, ensure_ascii=False))
        payload = {
            "model": self.model,
            "input": prompt,
            "text": {"format": {"type": "json_object"}},
        }
        req = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            # Different SDK/API versions expose output differently. This keeps the plugin conservative.
            text = ""
            for item in data.get("output", []) or []:
                for content in item.get("content", []) or []:
                    if content.get("type") in {"output_text", "text"}:
                        text += str(content.get("text") or "")
            parsed = json.loads(text) if text else []
            if isinstance(parsed, dict):
                parsed = parsed.get("translations") or parsed.get("items") or []
            if isinstance(parsed, list) and len(parsed) == len(texts):
                return [str(x) for x in parsed]
            return list(texts)
        except Exception:
            if self.fallback_to_original:
                return list(texts)
            raise
