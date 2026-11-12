# Comfy Vault custom nodes

These nodes send generation snapshots to a local Comfy Vault application. They do not load models or copy weights. You need a running archive server and ComfyUI. IMAGE capture also uses NumPy and Pillow, normally included with ComfyUI.

## Installation

Place this directory at `ComfyUI/custom_nodes/comfyui_vault` and restart ComfyUI. The entry point must be `ComfyUI/custom_nodes/comfyui_vault/__init__.py`. Do not install both `comfyui_vault` and the older `comfy_vault` package.

You can also download the package using **Connect ComfyUI** in the application. Preserve your `comfyui_vault.json` when replacing package files during updates.

## Archive Images

Connect a finished `IMAGE` and set `project` and `artifact`. The node saves the batch as PNG files, embeds the execution graph, and uploads a new version with detected references and dependencies. Outputs are the original `images` and a `version_url`.

If Save Image has no output, connect the same IMAGE to both nodes. Archive Images captures its completed branch without waiting for other independent branches. Repeating Queue creates a new version even when upstream results are cached.

Names are matched exactly and are case-sensitive. Projects are unique across the library; artifacts are unique within a project. New projects enter the default group, while existing projects retain their group. Update workflow names after renaming or moving objects.

## Archive Files

Archive existing files without re-encoding them. Set `project` and `artifact`, then use either:

- **VideoHelperSuite:** connect `VHS_FILENAMES` to `vhs_filenames`.
- **Other saving nodes:** enter one path per line in `files` and connect the saving node's output to `after`.

Absolute paths and names relative to `input` are supported, including ComfyUI annotations `[input]`, `[output]`, and `[temp]`. Files must be inside input/output/temp or `extra_input_roots`. Model weights are prohibited. The output is `version_url`.

Without a link to the saving branch, its parameters cannot be detected automatically. A node's visual position does not establish an execution dependency. Invalid or excessively long paths are rejected as unsuitable files.

## Capture Value

Pass `value` through unchanged and add it under `name` in the `metadata` output. Connect metadata to an archive node. Use `previous` to chain multiple Capture Value nodes.

```text
computed STRING → Capture Value (name=positive_prompt) → CLIP Text Encode
                     metadata ───────────────────────→ Archive Images.metadata
```

Small JSON-compatible values are supported: strings, numbers, booleans, null, lists, and dictionaries. The entire chain is validated, including previous. NaN, Infinity, tensors, and other nonserializable objects are rejected. The combined serialized metadata is limited to 1,048,576 characters.

Captured values appear in version metadata but do not rewrite the API graph or visual workflow. Fix computed parameters manually when restoring a generation.

## Configuration

The default URL is `http://127.0.0.1:8088`. No change is needed when ComfyUI runs on the same Mac where Docker publishes that port. If ComfyUI runs in another container or on another computer, use an address it can reach. Localhost refers to the ComfyUI process's own machine or container.

Copy `comfyui_vault.example.json` to `comfyui_vault.json` beside `capture.py`:

```json
{
  "url": "http://127.0.0.1:8088",
  "hash_models": true,
  "timeout": 600,
  "extra_input_roots": []
}
```

| Field | Purpose |
| --- | --- |
| `url` | Application address, without `/api/ingest` |
| `hash_models` | Compute model SHA-256 hashes; the first read of large weights can take time |
| `timeout` | HTTP connection timeout in seconds |
| `extra_input_roots` | Additional allowed file directories on the ComfyUI machine |

The `COMFY_VAULT_URL` environment variable overrides `url`. These are global node settings rather than workflow inputs. Local configuration files are excluded from Git and release ZIPs.

## Reliability and reproducibility

Archiving is synchronous. If the server is unavailable, the node fails; deferred uploads are not implemented. Keep a regular Save Image node as another copy of your results. Do not modify references or models while a generation is queued or running.

The complete graph is saved without the internal `is_changed` field that ComfyUI adds for caching and that may contain NaN. The live execution graph and generation parameters remain unchanged. Unrecognized dependencies produce warnings; arbitrary custom loaders may need adapters. Third-party node source code and model weights are not archived.

Restoration is manual. Identical parameters do not guarantee bit-identical output on different hardware or library versions.

## License

[Unlicense](LICENSE). You may use, modify, and distribute this code, including commercially, without warranties.
