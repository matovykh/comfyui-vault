# Validation and limitations

[← README](README.md) · [Development](CONTRIBUTING.md)

This document records checks that have actually been completed. A passing test with simulated data does not establish support for every workflow or bit-identical generation reproducibility.

## Automated checks

The current suite contains **32 Python tests** and a JavaScript interface-logic check.

```bash
python -m unittest discover -s tests -v
node tests/test_ui.cjs
node --check app/static/app.js
node --check app/static/i18n.js
python -m compileall -q app custom_nodes tests
bash -n start.command
docker compose config
```

Coverage includes:

- ZIP ingestion, file storage and downloads, workflows, parameters, environment records, and capture-ID idempotency.
- Exact uint64 seeds, branch selection, sampler-stage grouping, and no guesses about computed values.
- Concurrent version numbering, independent artifacts, and continuation after relocating a library.
- Invalid ZIPs, path traversal, undeclared files, incorrect SHA-256 hashes, and prohibited model weights.
- Long prompts and paths, filesystem errors, directory annotations, allowed roots, and symbolic links.
- Removing internal `is_changed` NaN values without mutating the live graph; PNG and ZIP handling through the real Archive Images/Archive Files methods and TestClient API.
- Capture Value metadata chains, exact seeds, long text, rejection of NaN/Infinity and unsupported objects, and chain-size limits.
- Groups, renaming, moves, cascading deletion, preservation of moved files when deleting the original project, and empty libraries.
- Export and restoration, favorites and notes, invalid backups leaving current data intact, and selected-directory persistence across restarts.
- JavaScript tree logic, artifact selection, favorites, media navigation, cancel-on-Enter, theme switches, labels, and SVG icons.
- Contrast calculation for nine semantic text/background pairs in dark, light, and system-light palettes: at least 4.5:1 for the tested pairs.

The latest full run used macOS with Python 3.13, FastAPI 0.136.3, and httpx 0.28.1 in the available development environment. Production dependencies are pinned separately in requirements.txt; this run is not a test of the final Docker image.

## Manual interface checks

Safari was tested without extensions, using a separate test library and synthetic images:

- Empty General group and creation of projects and artifacts with Russian names and descriptions.
- Three-version history, favorites excluding the middle version, full-resolution viewing, and button navigation between the remaining results.
- Deletion confirmation and cancellation with Enter without deleting data.
- Settings, English/Chinese labels, light/dark themes, and synchronized system-theme switches.
- SVG tree icons, ellipsized artifact descriptions with project-description fallback, readable LoRA names and strengths, and media-type icons beside version numbers.
- Font-size adjustment from 16 to 13 px and persistence after refreshing the page.

The user also confirmed a successful real Archive Images generation after the long-path and NaN fixes. This establishes that particular run's success, not complete dependency coverage for every third-party node.

## Public repository preparation

Documentation was checked against the current API, Compose setup, settings, and nodes. Local links and both README illustrations were checked. Ignore rules were verified in a temporary Git repository: databases, local configuration, weights, environments, and machine files are excluded, while documentation, LICENSE, illustrations, and configuration examples remain trackable.

Both release ZIPs were built and checked for integrity. The source archive includes README, illustrations, .gitignore, .env.example, and CONTRIBUTING.md. Unlicense is included in both source and node packages. Packaging excludes local configuration, databases, weights, credentials, and development state. All 32 Python tests and the JavaScript checks passed after the packaging changes.

All six Markdown documents have been translated into English. The guide is now QUICKSTART.md. README uses standard Markdown images instead of HTML wrappers; checks cover raw HTML tags, remaining Cyrillic text, local links, heading anchors, and fenced JSON examples.

## Container delivery

An early Linux validation covered Docker builds, healthchecks, ZIP transmission, repeated captures, and persistence after container recreation. Compose configuration was checked again after the API and interface expansion, but the current image has not repeated the entire earlier scenario. Early results should not be interpreted as validation of every later change.

## Scenarios requiring separate verification

- Real videos and codec compatibility in each browser.
- Narrow mobile viewports and all combinations of long content and extreme font sizes.
- Keyboard media navigation in a real browser: implemented, but not confirmed through native automation.
- Custom loaders, hidden dependencies, dynamic subgraphs, and files outside recognized fields.
- The final Docker image with pinned dependencies after the latest changes.
- Bit-identical generation on different hardware and software environments.

Browser checks and documentation work did not modify the user's working library. The user supplied app_example.png and node_example.png as application illustrations.
