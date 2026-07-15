# Model weights

This directory holds the ONNX model used for orientation detection. The `.onnx` file itself is
gitignored (it's an ~80MB binary) -- you need to place it here yourself before running the
script. `--model-path` defaults to `models/best_model.onnx` relative to this directory.

Get it one of two ways:

1. **Copy from a local checkout of `deep-image-orientation-detection`**, if you already have the
   v2 model downloaded there:
   ```bash
   cp /path/to/deep-image-orientation-detection/models/best_model.onnx models/best_model.onnx
   ```
2. **Download directly** from the `deep-image-orientation-detection` v2 release:
   https://github.com/duartebarbosadev/deep-image-orientation-detection/releases/tag/v2
   -- grab `orientation_model_v2_0.9882.onnx` and save it here as `best_model.onnx`.

See [`../docs/how-it-works.md`](../docs/how-it-works.md) for what the model does and how it's
used.
