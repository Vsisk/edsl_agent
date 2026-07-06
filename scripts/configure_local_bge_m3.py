from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path


SETTINGS = {
    "EMBEDDING_PROVIDER": "local_bge_m3",
    "OPENAI_EMBEDDING_MODEL": "bge-m3",
    "LOCAL_EMBEDDING_MODEL_PATH": r"D:\models\bge-m3",
    "LOCAL_EMBEDDING_DEVICE": "cuda",
    "LOCAL_EMBEDDING_BATCH_SIZE": "8",
    "LOCAL_EMBEDDING_MAX_LENGTH": "4096",
    "LOCAL_EMBEDDING_NORMALIZE": "true",
}


def update_env(path: Path) -> None:
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = original.splitlines()
    replaced: set[str] = set()
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else ""
        if key in SETTINGS:
            if key not in replaced:
                result.append(f"{key}={SETTINGS[key]}")
                replaced.add(key)
            continue
        result.append(line)
    if result and result[-1] != "":
        result.append("")
    for key, value in SETTINGS.items():
        if key not in replaced:
            result.append(f"{key}={value}")
    content = "\n".join(result).rstrip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"Configured {len(SETTINGS)} local embedding settings in {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure local BGE-M3 settings without changing other .env values.")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    update_env(args.env_file.resolve())


if __name__ == "__main__":
    main()
