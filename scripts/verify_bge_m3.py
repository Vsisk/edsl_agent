from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.context_manager.retrieval.local_bge_m3 import LocalBGEM3Provider
from agent.llm.config import OpenAISettings


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify local BGE-M3 dense embeddings.")
    parser.add_argument("--model-dir", type=Path, default=Path(r"D:\models\bge-m3"))
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    args = parser.parse_args()
    settings = OpenAISettings(
        enabled=True, api_key="", base_url=None, base_model="unused", vl_model="unused",
        timeout_seconds=30, embedding_model="bge-m3", embedding_provider="local_bge_m3",
        local_embedding_model_path=str(args.model_dir), local_embedding_device=args.device,
        local_embedding_batch_size=2, local_embedding_max_length=4096,
        local_embedding_normalize=True,
    )
    provider = LocalBGEM3Provider(settings)
    vectors = provider.embed_texts([
        "查询当前账期费用", "Retrieve charges for the current billing cycle",
    ])
    if len(vectors) != 2 or any(len(vector) != 1024 for vector in vectors):
        raise SystemExit(f"Unexpected embedding shape: {[len(vector) for vector in vectors]}")
    norms = [math.sqrt(sum(value * value for value in vector)) for vector in vectors]
    if not all(math.isfinite(value) and abs(value - 1.0) < 1e-3 for value in norms):
        raise SystemExit(f"Embeddings are not finite normalized vectors: {norms}")
    print(f"requested_device={args.device} effective_device={provider.effective_device} "
          f"shape=(2, 1024) norms={[round(value, 6) for value in norms]}")


if __name__ == "__main__":
    main()
