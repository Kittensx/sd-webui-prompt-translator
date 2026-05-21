import argparse
import json
from pathlib import Path

from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

LANGUAGE_CODES = {
    "en": "eng_Latn",
    "ja": "jpn_Jpan",
    "es": "spa_Latn",
    "fr": "fra_Latn",
    "de": "deu_Latn",
}

DEFAULT_MODEL = "facebook_nllb-200-distilled-600M"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--source", default="en")
    parser.add_argument("--target", default="ja")
    parser.add_argument("--models-dir", default="./models")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    model_path = (
        Path(args.models_dir)
        / "nllb"
        / DEFAULT_MODEL
    )

    tokenizer = AutoTokenizer.from_pretrained(str(model_path))
    model = AutoModelForSeq2SeqLM.from_pretrained(str(model_path))

    source_lang = LANGUAGE_CODES[args.source]
    target_lang = LANGUAGE_CODES[args.target]

    tokenizer.src_lang = source_lang

    encoded = tokenizer(args.text, return_tensors="pt")

    generated_tokens = model.generate(
        **encoded,
        forced_bos_token_id=tokenizer.convert_tokens_to_ids(target_lang),
        max_length=128,
    )

    translated = tokenizer.batch_decode(
        generated_tokens,
        skip_special_tokens=True,
    )[0]

    result = {
        "input": args.text,
        "source_language": args.source,
        "target_language": args.target,
        "translation": translated,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"INPUT:       {args.text}")
        print(f"TRANSLATED:  {translated}")

if __name__ == "__main__":
    main()
