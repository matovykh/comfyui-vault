# Contributing to Comfy Vault

[← README](README.md)

## Local environment

Use Python 3.12+ and Node.js for JavaScript checks. Docker is needed to test container delivery, and ComfyUI is needed for real generations.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m app --data-dir /tmp/comfy-vault-dev
```

Use a separate test library. Keep real generation data, local configuration, and weights out of Git, issue reports, and test fixtures.

## Project structure

| Path | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI, HTTP API, library switching, and import |
| `app/store.py` | SQLite, version files, ingestion, export, moves, and deletion |
| `app/metadata.py` | Parameter extraction from graph branches and browser-safe values |
| `app/static/` | Interface, themes, shared typography, and translations |
| `custom_nodes/comfyui_vault/` | ComfyUI nodes and capture ZIP creation |
| `tests/` | Server, node, contrast, and JavaScript logic tests |
| `scripts/package.py` | Source ZIP and custom-node package creation |

The frontend does not need an npm build. SVG icons are embedded in the code; no external fonts are loaded. Colors and typography use tokens in style.css, and all text scales from the root font size. Add interface labels in English, Russian, and Chinese; do not translate user content.

## Checks before changing a release

```bash
python -m unittest discover -s tests -v
node tests/test_ui.cjs
node --check app/static/app.js
node --check app/static/i18n.js
python -m compileall -q app custom_nodes tests
bash -n start.command
docker compose config
```

Check the interface in a browser: light/dark/system themes, font size, long names, an empty library, and deletion confirmation. The JavaScript DOM adapter is not a substitute for browser testing. Test real video codecs separately.

Test capture changes in an installed ComfyUI using a real IMAGE, a reference file, an exact seed, a custom loader, and a repeated Queue. Tests use IMAGE/folder_paths stand-ins and do not establish diffusion reproducibility.

## Release packages

```bash
python scripts/package.py /tmp/comfy-vault-release
```

This creates `comfy-vault.zip` with sources and `comfyui_vault.zip` with the node folder. Both include Unlicense. Keep local libraries and secrets outside the source tree: `.gitignore` governs Git, not every external archive tool.

Describe the resulting behavior, validation, and limitations when submitting changes. Storage-schema changes should provide a migration or a clear refusal to open an unsupported schema, with updated FORMAT.md documentation. Keep the record of completed checks in VALIDATION.md current.

Documentation uses standard Markdown, including Markdown image syntax. Avoid raw HTML wrappers so local Markdown viewers and GitHub render the same content. Check relative links and heading anchors whenever files or headings change.

## License

The project uses [Unlicense](LICENSE). Contribute material that can be distributed on those terms. Third-party dependencies retain their own licenses.
