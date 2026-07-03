# Local BGE-M3 Embedding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a locally downloaded `BAAI/bge-m3` model inside the application process with CUDA FP16 and make it the configured Context Manager embedding provider.

**Architecture:** Extend existing OpenAI settings with provider-local fields, split embedding implementations behind the existing `EmbeddingClientProtocol`, and lazily cache a local SentenceTransformer model per path/device. Reproducible uv scripts create Python 3.12 `.venv`, install pinned dependencies, download a pinned Hugging Face snapshot to `D:\models\bge-m3`, and verify real 1024-dimensional normalized embeddings.

**Tech Stack:** Python 3.12, uv, PyTorch CUDA, sentence-transformers, transformers, huggingface-hub, pytest.

---

### Task 1: Add Provider Configuration

**Files:**
- Modify: `agent/llm/config.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `agent/context_manager/README.md`
- Test: `tests/test_context_retrieval.py`

- [ ] **Step 1: Write failing configuration tests**

Assert defaults and environment overrides for:

```python
assert settings.embedding_provider == "local_bge_m3"
assert settings.embedding_model == "bge-m3"
assert settings.local_embedding_model_path == r"D:\models\bge-m3"
assert settings.local_embedding_device == "cuda"
assert settings.local_embedding_batch_size == 8
assert settings.local_embedding_max_length == 4096
assert settings.local_embedding_normalize is True
```

- [ ] **Step 2: Run the focused test and observe failure**

Run: `python -m pytest tests/test_context_retrieval.py -q`

Expected: FAIL because local embedding settings do not exist.

- [ ] **Step 3: Implement immutable settings and parsing**

Add fields to `OpenAISettings` with backward-compatible trailing defaults. Parse the seven environment keys using existing helpers plus a positive-integer helper. Reject invalid provider values later in the provider factory so settings loading stays side-effect free.

- [ ] **Step 4: Update tracked configuration and docs**

Set `OPENAI_EMBEDDING_MODEL=bge-m3`, add all local provider keys to `.env.example`, and document that local provider does not use `OPENAI_BASE_URL` for embedding requests.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_context_retrieval.py tests/test_llm_integration.py -q`

Commit: `feat: configure local bge-m3 embeddings`

### Task 2: Implement the In-Process Provider

**Files:**
- Create: `agent/context_manager/retrieval/local_bge_m3.py`
- Modify: `agent/context_manager/retrieval/embedding_client.py`
- Modify: `agent/context_manager/retrieval/__init__.py`
- Test: `tests/test_local_bge_m3.py`
- Test: `tests/test_context_retrieval.py`

- [ ] **Step 1: Write failing provider tests using fake loaders**

Cover empty input, lazy load, cache reuse, concurrent first load, CUDA FP16/CPU FP32 loader arguments, batch/max-length/normalize propagation, order, finite vectors, dimension mismatch, missing path, invalid device, and stable error mapping.

- [ ] **Step 2: Run tests and observe missing provider failure**

Run: `python -m pytest tests/test_local_bge_m3.py -q`

Expected: FAIL because `LocalBGEM3Provider` does not exist.

- [ ] **Step 3: Implement a lazy lock-protected model cache**

Expose:

```python
class LocalBGEM3Provider:
    def __init__(self, settings: OpenAISettings, model_loader=None): ...
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
```

The default loader imports Torch and SentenceTransformer only on first non-empty call. Cache key is canonical model path plus resolved device. Use one class-level lock and cache dictionary. CUDA loads with `torch.float16`; CPU loads with `torch.float32`. Set the model maximum sequence length from configuration and call `encode(..., batch_size=..., normalize_embeddings=..., convert_to_numpy=True)`.

- [ ] **Step 4: Validate provider output**

Convert NumPy/Torch output to plain `list[list[float]]`, require one nonempty finite vector per input, consistent dimensions, and preserve order. Map configuration errors to `AI_CONFIGURATION_REQUIRED`; import/load/encode/shape errors to sanitized `EMBEDDING_FAILED`.

- [ ] **Step 5: Delegate from EmbeddingClient**

`EmbeddingClient` selects `local_bge_m3` or `openai` once from settings. Keep existing OpenAI behavior intact and reject unknown providers with `AI_CONFIGURATION_REQUIRED`. Allow provider injection in tests without installing Torch.

- [ ] **Step 6: Verify and commit**

Run: `python -m pytest tests/test_local_bge_m3.py tests/test_context_retrieval.py tests/test_context_manager_namingsql.py -q`

Commit: `feat: load bge-m3 embeddings in process`

### Task 3: Add Reproducible Environment and Model Scripts

**Files:**
- Create: `requirements-local-bge-m3.txt`
- Create: `scripts/setup_local_bge_m3.ps1`
- Create: `scripts/download_bge_m3.py`
- Create: `scripts/verify_bge_m3.py`
- Modify: `.gitignore`
- Modify: `agent/context_manager/README.md`

- [ ] **Step 1: Pin compatible dependencies**

Record pinned Python 3.12-compatible versions for torch, sentence-transformers, transformers, huggingface-hub, safetensors, numpy, OpenAI, Pydantic, jsonpath-ng, and pytest. Use the PyTorch CUDA wheel index in the setup script rather than an invalid requirements directive.

- [ ] **Step 2: Implement the setup script**

The PowerShell script must:

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe torch --index-url https://download.pytorch.org/whl/cu128
uv pip install --python .venv\Scripts\python.exe -r requirements-local-bge-m3.txt
```

It must stop on errors and print exact verification commands. `.venv/` must be ignored.

- [ ] **Step 3: Implement pinned model download**

`download_bge_m3.py` calls `snapshot_download(repo_id="BAAI/bge-m3", revision=<pinned commit>, local_dir=Path(...))`, supports `--model-dir`, and writes a small local revision marker after success. It never logs tokens.

- [ ] **Step 4: Implement real-model verification**

`verify_bge_m3.py` loads the project provider, embeds one Chinese and one English sentence, and asserts two finite 1024-dimensional vectors with norms close to one. It prints device, shape, and norms but no environment secrets.

- [ ] **Step 5: Verify scripts and commit**

Run script help/compile checks and the existing fake-provider tests.

Commit: `build: add local bge-m3 bootstrap scripts`

### Task 4: Install, Download, Configure, and Verify This Machine

**Files:**
- Modify locally only: `.env`
- Create outside repository: `D:\models\bge-m3\...`

- [ ] **Step 1: Create `.venv` and install dependencies**

Run: `powershell -ExecutionPolicy Bypass -File scripts/setup_local_bge_m3.ps1`

Expected: `.venv\Scripts\python.exe` imports Torch, Transformers, SentenceTransformers, and Hugging Face Hub; `torch.cuda.is_available()` is true.

- [ ] **Step 2: Download the pinned model snapshot**

Run: `.venv\Scripts\python.exe scripts\download_bge_m3.py --model-dir D:\models\bge-m3`

Expected: complete snapshot and revision marker exist.

- [ ] **Step 3: Update local `.env` safely**

Insert or replace only the seven embedding keys from the approved design. Preserve all other values and never print credentials.

- [ ] **Step 4: Verify the real model on GPU**

Run: `.venv\Scripts\python.exe scripts\verify_bge_m3.py --model-dir D:\models\bge-m3 --device cuda`

Expected: CUDA device, shape `(2, 1024)`, finite near-unit norms.

- [ ] **Step 5: Run the project suite in `.venv`**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Record machine verification and commit tracked changes**

Do not commit `.env`, `.venv`, or model weights. Commit only source, tests, scripts, requirements, docs, and examples.
