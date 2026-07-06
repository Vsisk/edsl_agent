from __future__ import annotations

import argparse
from pathlib import Path

REPO_ID = "BAAI/bge-m3"
REVISION = "5617a9f61b028005a4858fdac845db406aefb181"


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the pinned BGE-M3 model snapshot.")
    parser.add_argument("--model-dir", type=Path, default=Path(r"D:\models\bge-m3"))
    args = parser.parse_args()
    from huggingface_hub import snapshot_download

    model_dir = args.model_dir.expanduser().resolve()
    model_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=REPO_ID,
        revision=REVISION,
        local_dir=model_dir,
        ignore_patterns=["onnx/**", "*.onnx", "*.onnx_data"],
    )
    (model_dir / ".bge-m3-revision").write_text(REVISION + "\n", encoding="utf-8")
    print(f"Downloaded {REPO_ID} revision {REVISION} to {model_dir}")


if __name__ == "__main__":
    main()
