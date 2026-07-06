# Local BGE-M3 Embedding Design

## Goal

Run `BAAI/bge-m3` inside the application process for Context Manager semantic recall, using the local RTX 4060 Ti GPU. Download the weights once to `D:\models\bge-m3`, configure the project to use them by default, and retain the existing OpenAI-compatible embedding provider as an explicit alternative.

## Runtime

The system Python 3.14 environment will not be modified. A project-local `.venv` will be created with uv-managed CPython 3.12 because it has mature PyTorch and Transformers support. Application commands that use local embeddings must run through this environment.

The environment will install:

- CUDA-enabled PyTorch compatible with the installed NVIDIA driver;
- `sentence-transformers`;
- `transformers`;
- `huggingface-hub`;
- existing project runtime and test dependencies required by the repository.

The virtual environment remains ignored by Git. Dependency versions and bootstrap commands will be recorded in tracked project files or scripts so the environment can be reproduced.

## Model Storage and Download

Weights will be downloaded from the official `BAAI/bge-m3` Hugging Face repository into:

```text
D:\models\bge-m3
```

The download must use `huggingface_hub.snapshot_download` with a pinned model revision recorded in configuration or documentation. The model directory remains outside the repository and is never committed.

After download, verification must confirm that the snapshot is complete and that the model can produce a finite, normalized 1024-dimensional dense embedding for Chinese and English sample text.

## Configuration

Add the following settings:

```dotenv
EMBEDDING_PROVIDER=local_bge_m3
OPENAI_EMBEDDING_MODEL=bge-m3
LOCAL_EMBEDDING_MODEL_PATH=D:\models\bge-m3
LOCAL_EMBEDDING_DEVICE=cuda
LOCAL_EMBEDDING_BATCH_SIZE=8
LOCAL_EMBEDDING_MAX_LENGTH=4096
LOCAL_EMBEDDING_NORMALIZE=true
```

`OPENAI_EMBEDDING_MODEL` changes from `text-embedding-3-small` to `bge-m3` for consistent model identity. The provider decides whether the identity is resolved locally or sent to an OpenAI-compatible endpoint.

The same non-secret values will be added to `.env.example`; the local `.env` will be updated without exposing or replacing existing credentials.

## Embedding Architecture

`agent.context_manager.retrieval.EmbeddingClient` remains the business-facing interface. It delegates to one of two providers:

- `local_bge_m3`: an in-process `SentenceTransformer` provider;
- `openai`: the existing OpenAI-compatible embeddings implementation.

The local provider:

- validates that the configured model directory exists;
- selects CUDA only when available and explicitly requested;
- when `cuda` is configured but `torch.cuda.is_available()` is false, resolves the
  effective device to CPU and loads FP32 automatically;
- loads the model lazily on the first non-empty request;
- maintains one process-wide model instance per canonical `(model_path, device)` key;
- uses FP16 on CUDA and FP32 on CPU;
- encodes batches with the configured maximum length and batch size;
- returns normalized dense vectors in input order;
- rejects non-finite or malformed vectors with the existing `EMBEDDING_FAILED` error;
- returns an empty list for empty input without loading the model.

The model cache must be lock-protected so concurrent first requests do not load duplicate GPU copies. Tests must be able to inject a fake model loader without importing or loading PyTorch weights.

CUDA fallback is deliberately narrow. CUDA model-load failures, allocation errors,
out-of-memory errors, and inference failures remain `EMBEDDING_FAILED`; they do not
trigger a second CPU load. This keeps genuine GPU/driver faults visible instead of
silently changing latency and capacity characteristics.

## Failure Behavior

Local provider failures remain fail-closed:

- missing model path or unusable device configuration: `AI_CONFIGURATION_REQUIRED`;
- import, model-load, CUDA allocation, encoding, or output-shape failures: `EMBEDDING_FAILED`;
- no automatic switch from local to remote embeddings after a local failure.

Failing over between providers requires an explicit configuration change. This prevents semantically incompatible embeddings from being mixed silently.

## Integration and Compatibility

`SemanticRetriever`, `HybridRetriever`, resolvers, Selector, and Planner contracts do not change. Only the concrete embedding provider and settings are extended.

The existing OpenAI-compatible provider remains testable and selectable with:

```dotenv
EMBEDDING_PROVIDER=openai
OPENAI_EMBEDDING_MODEL=<remote-model-name>
```

The existing LLM configuration and base URL are unaffected.

## Verification

Automated tests will cover:

- provider selection and configuration parsing;
- lazy load and empty-input behavior;
- process-wide cache reuse and concurrent first load;
- FP16/CUDA and FP32/CPU selection through fakes;
- batch size, maximum length, normalization, ordering, and vector validation;
- stable error mapping without local paths or sensitive details leaking publicly;
- unchanged OpenAI provider behavior;
- unchanged Context Manager retrieval tests.

Environment verification will then:

1. create `.venv` with Python 3.12;
2. install pinned dependencies;
3. download the pinned Hugging Face snapshot;
4. load it on CUDA;
5. embed Chinese and English samples;
6. assert shape `(2, 1024)`, finite values, and near-unit norms;
7. run the project test suite from `.venv`.
