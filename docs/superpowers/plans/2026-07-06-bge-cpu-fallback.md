# BGE-M3 CPU Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve configured CUDA to CPU FP32 when CUDA is unavailable, without hiding CUDA load or inference failures.

**Architecture:** Device resolution happens before the process-wide model cache key is created. A small injectable CUDA-availability probe keeps tests independent of Torch; the resolved device controls both cache identity and FP16 selection.

**Tech Stack:** Python, PyTorch runtime probe, pytest.

---

### Task 1: Resolve the Effective Device

**Files:**
- Modify: `agent/context_manager/retrieval/local_bge_m3.py`
- Modify: `tests/test_local_bge_m3.py`

- [ ] **Step 1: Add failing tests**

Add tests proving configured CUDA plus unavailable probe calls the loader with `("cpu", False)`, uses a CPU cache key, and still returns embeddings. Add a test proving a CUDA loader exception remains `EMBEDDING_FAILED` and does not invoke a CPU loader.

- [ ] **Step 2: Run the focused tests**

Run: `python -m pytest tests/test_local_bge_m3.py -q`

Expected: the unavailable-CUDA test fails because current code raises `AI_CONFIGURATION_REQUIRED` in the default loader.

- [ ] **Step 3: Implement device resolution**

Inject an optional `cuda_available` callable. For configured `cuda`, resolve to `cuda` when the probe is true and `cpu` otherwise. For configured `cpu`, do not call the probe. Pass the resolved device into the cache key and pass `use_fp16=(device == "cuda")` to the loader. Do not catch a CUDA load/encode error and retry CPU.

- [ ] **Step 4: Verify**

Run: `python -m pytest tests/test_local_bge_m3.py tests/test_context_retrieval.py -q`

Expected: all tests pass.

### Task 2: Document and Validate Runtime Behavior

**Files:**
- Modify: `agent/context_manager/README.md`
- Modify: `scripts/verify_bge_m3.py`

- [ ] **Step 1: Document narrow fallback semantics**

State that configured CUDA falls back only when CUDA is not detected; load, OOM, and inference failures remain failures.

- [ ] **Step 2: Display the effective device**

Expose a read-only effective-device resolver or provider property and have the verification script report the resolved device rather than only the requested CLI value.

- [ ] **Step 3: Run all tests and commit**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass.

Commit: `feat: fall back to cpu when cuda is unavailable`
