from __future__ import annotations

"""
NLLB offline translation provider.

This provider loads a locally downloaded NLLB Hugging Face model from:
  <models_dir>/nllb/facebook_nllb-200-distilled-600M

It intentionally lazy-imports transformers/torch so the full backend can load even
when NLLB dependencies are not installed.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from language.constants import DEFAULT_NLLB_LOCAL_NAME, DEFAULT_NLLB_MODEL_ID, PROVIDER_ID_NLLB
    from language.paths import MODELS_DIR
except ImportError:
    try:
        from ..constants import DEFAULT_NLLB_LOCAL_NAME, DEFAULT_NLLB_MODEL_ID, PROVIDER_ID_NLLB
        from ..paths import MODELS_DIR
    except ImportError:
        from constants import DEFAULT_NLLB_LOCAL_NAME, DEFAULT_NLLB_MODEL_ID, PROVIDER_ID_NLLB
        from paths import MODELS_DIR

try:
    from language.language_utils import canonical_lang
except Exception:
    try:
        from ..language_utils import canonical_lang
    except Exception:
        from language_utils import canonical_lang

NLLB_LANGUAGE_CODES: Dict[str, str] = {
    "en": "eng_Latn",
    "ja": "jpn_Jpan",
    "es": "spa_Latn",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "it": "ita_Latn",
    "pt": "por_Latn",
    "ko": "kor_Hang",
    "zh": "zho_Hans",
    "ru": "rus_Cyrl",
    "ar": "arb_Arab",
    "hi": "hin_Deva",
    "nl": "nld_Latn",
    "pl": "pol_Latn",
    "tr": "tur_Latn",
    "id": "ind_Latn",
    "vi": "vie_Latn",
    "th": "tha_Thai",
}

# Reuse loaded models across provider instances and roundtrip stages.
# This prevents repeated "Loading weights" messages when tests translate many spans.
_NLLB_MODEL_CACHE: Dict[Tuple[str, str], Tuple[object, object]] = {}


def safe_model_name(model_id: str) -> str:
    return model_id.replace("/", "_")


@dataclass
class Provider:
    """Local NLLB provider. Uses CPU by default unless device is provided."""

    models_dir: str | Path = MODELS_DIR
    model_id: str = DEFAULT_NLLB_MODEL_ID
    local_name: Optional[str] = None
    device: Optional[str] = None  # None, "cpu", "cuda"
    max_length: int = 128
    name: str = PROVIDER_ID_NLLB

    _tokenizer: object = field(default=None, init=False, repr=False)
    _model: object = field(default=None, init=False, repr=False)
    _loaded_key: Optional[Tuple[str, str]] = field(default=None, init=False, repr=False)

    def model_path(self) -> Path:
        local = self.local_name or safe_model_name(self.model_id)
        root = Path(self.models_dir).expanduser().resolve()
        # Accept either ./models/nllb/<model> or direct ./models/<model>
        p1 = root / "nllb" / local
        if p1.exists():
            return p1
        return root / local

    def is_available(self) -> bool:
        path = self.model_path()
        return path.exists() and any(path.iterdir())

    def _load(self):
        path = self.model_path()
        if not path.exists():
            raise RuntimeError(
                f"NLLB model not found at {path}. Download it with provider_model_manager.py install-nllb-pair/install-nllb-bundle."
            )

        cache_key = (str(path.resolve()), str(self.device or "cpu"))
        cached = _NLLB_MODEL_CACHE.get(cache_key)
        if cached is not None:
            self._tokenizer, self._model = cached
            return

        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except Exception as e:
            raise RuntimeError(
                "NLLB provider requires transformers and sentencepiece. Install with: "
                "pip install transformers sentencepiece huggingface_hub"
            ) from e

        self._tokenizer = AutoTokenizer.from_pretrained(str(path))
        self._model = AutoModelForSeq2SeqLM.from_pretrained(str(path))
        if self.device:
            try:
                self._model.to(self.device)
            except Exception as e:
                raise RuntimeError(f"Could not move NLLB model to device {self.device!r}: {e!r}") from e
        _NLLB_MODEL_CACHE[cache_key] = (self._tokenizer, self._model)

    def translate_texts(self, texts: List[str], *, source_language: str, target_language: str) -> List[str]:
        src = canonical_lang(source_language)
        tgt = canonical_lang(target_language)
        src_code = NLLB_LANGUAGE_CODES.get(src)
        tgt_code = NLLB_LANGUAGE_CODES.get(tgt)
        if not src_code or not tgt_code:
            raise RuntimeError(f"NLLB language pair not configured: {src}->{tgt}")
        if src == tgt:
            return list(texts)
        if self._model is None or self._tokenizer is None:
            self._load()

        tok = self._tokenizer
        model = self._model
        tok.src_lang = src_code

        out: List[str] = []
        for text in texts:
            if not isinstance(text, str) or not text.strip():
                out.append(text)
                continue
            encoded = tok(text, return_tensors="pt")
            if self.device:
                try:
                    encoded = {k: v.to(self.device) for k, v in encoded.items()}
                except Exception:
                    pass
            generated = model.generate(
                **encoded,
                forced_bos_token_id=tok.convert_tokens_to_ids(tgt_code),
                max_length=int(self.max_length or 128),
            )
            out.append(tok.batch_decode(generated, skip_special_tokens=True)[0])
        return out


NLLBTranslationProvider = Provider
