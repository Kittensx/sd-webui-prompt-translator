import argparse
from pathlib import Path
import os

from huggingface_hub import snapshot_download
HF_TOKEN = os.getenv("HF_TOKEN")


DEFAULT_MODEL = "facebook/nllb-200-distilled-600M"

def safe_name(name: str) -> str:
    return name.replace("/", "_")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--models-dir", default="./models")
    args = parser.parse_args()

    model_dir = Path(args.models_dir) / "nllb" / safe_name(args.model)
    model_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {args.model}")
    print(f"Destination: {model_dir}")

    snapshot_download(
        repo_id=args.model,
        local_dir=str(model_dir),
        local_dir_use_symlinks=False,
        token=HF_TOKEN,
    )

    print("Done.")

if __name__ == "__main__":
    main()
