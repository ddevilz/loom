---
description: Manual intervention issues and recovery notes
---

# Manual Intervention Errors

## Embedding model cache missing or corrupted

### Symptom

`loom analyze` completes with an `embed` phase error similar to:

```text
[ONNXRuntimeError] : 3 : NO_SUCHFILE : ... model.onnx failed. File doesn't exist
```

### Cause

The local `fastembed` model cache is incomplete or corrupted. This can happen if a model download was interrupted or if a temporary cache location was cleaned up.

### Current mitigation in Loom

Loom now:

- uses a stable embedding cache directory by default
- retries embedding once by recreating the `fastembed` model handle
- attempts to avoid volatile temp-cache paths

### Manual intervention if it still fails

Remove the cached embedding model directory and rerun analysis.

Default stable cache path:

```text
C:\Users\<your-user>\.loom\fastembed_cache
```

You can also override the location with:

```text
LOOM_EMBED_CACHE_DIR
```

## Analyze target is a subfolder, not repo root

### Symptom

Coupling analysis reports that the target path is not a valid git repository.

### Cause

The analyze target is a subfolder inside a repo instead of the repo root.

### Current mitigation in Loom

Loom now resolves the nearest parent git repository for coupling analysis.

### Manual intervention if it still fails

Run analyze from the repo root or verify that the target path is inside a valid git repository.
