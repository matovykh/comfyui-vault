# API and storage format

[← README](README.md)

The application exposes an HTTP API at `http://127.0.0.1:8088`. OpenAPI is available at `/openapi.json`; interactive Swagger/ReDoc pages are disabled. Authentication is not implemented. The API is intended for local use.

## Capture package v1

`POST /api/ingest`, with `Content-Type: application/zip`.

The ZIP contains `capture.json` at its root and only the input/output files declared there. Paths must be relative, use `/`, and contain no `..`, absolute paths, symbolic links, backslashes, or duplicate entries. Model-weight files are not accepted.

```json
{
  "schema_version": 1,
  "capture_id": "226be5f3-3e4a-47f5-8ef8-e7a3fdf417cb",
  "project": "My project",
  "artifact": "Cover",
  "archive_node_id": "42",
  "prompt": {
    "42": {"class_type": "ComfyVaultArchiveImages", "inputs": {}}
  },
  "workflow": {"nodes": [], "links": [], "version": 0.4},
  "environment": {},
  "overrides": {"positive_prompt": "captured runtime value"},
  "models": [
    {
      "name": "model.safetensors",
      "category": "diffusion_models",
      "comfy_path": "models/diffusion_models/model.safetensors",
      "node_id": "1",
      "input": "unet_name",
      "sha256": null,
      "resolved": true
    }
  ],
  "warnings": [],
  "files": [
    {"path": "outputs/0000_image.png", "role": "output", "name": "image.png", "batch_index": 0},
    {"path": "inputs/0001_ref.png", "role": "input", "name": "ref.png", "comfy_path": "input/ref.png", "node_id": "3", "input": "image", "source_value": "ref.png"}
  ]
}
```

### Fields and limits

| Field | Rule |
| --- | --- |
| `schema_version` | Capture package version; currently `1` |
| `capture_id` | UUID; retrying the same ID returns the existing version |
| `project`, `artifact` | Nonempty names up to 160 characters; surrounding whitespace is removed |
| `prompt` | Required, nonempty API graph |
| `archive_node_id` | Branch root used to extract parameters for version cards |
| `workflow` | Visual graph, if available |
| `overrides` | Values supplied through metadata/Capture Value |
| `models` | Dependency list; weights are not included |
| `environment`, `warnings` | Environment details and completeness warnings |
| `files` | File descriptors; at least one `output` is required |

Files must be under `inputs/` or `outputs/`, with exactly one ZIP entry per descriptor. For inputs, `comfy_path` describes a destination relative to ComfyUI, such as `input/reference.png`. An archived filename may differ from its original name.

If supplied, `sha256` is verified on ingestion. The server always records the SHA-256 hash and size of received file bytes. Limits are 100 GB per uploaded package, 100 GB of declared uncompressed data, 10,000 ZIP entries, and 32 MB for `capture.json`. Temporary and final copies both consume disk space during ingestion.

JSON must contain only finite numeric values. The custom node removes only the internal `is_changed` field from node records. ComfyUI adds this cache field during execution, and it can contain NaN. The same cleanup applies to the API graph embedded in PNG metadata. Inputs, seeds, links, and other fields are preserved; the live graph is not mutated.

Successful ingestion returns HTTP 201:

```json
{"id":"...","number":1,"project_id":"...","artifact_id":"...","duplicate":false}
```

A repeated capture ID also returns HTTP 201, with `{"id":"...","duplicate":true}`. A new Queue creates a new UUID and version. Numbers are assigned transactionally per artifact; deleted numbers are not reused.

Card parameters come from ancestors of `archive_node_id`; the full API graph is stored separately. Large integers in browser-facing metadata are strings, while the original numeric seeds remain exact in `prompt.json`. Overrides supplement metadata rather than rewriting the workflow.

## Library management

POST/PATCH bodies use `application/json`. Object identifiers below are written as `{id}`.

| Method and path | Purpose |
| --- | --- |
| `GET /api/health` | Health and schema version |
| `GET /api/library` | `{groups, projects}`; projects include artifacts with `version_count`, `media_type`, and `latest` |
| `POST /api/groups` | Create a group: `{name}` |
| `PATCH /api/groups/{id}` | Rename a group: `{name}` |
| `POST /api/projects` | Create a project: `{name, description?, group_id?}` |
| `PATCH /api/projects/{id}` | Update `name`, `description`, or `group_id`; changing group_id moves the project |
| `POST /api/artifacts` | Create an artifact: `{project_id, name, description?, media_type?}` |
| `PATCH /api/artifacts/{id}` | Update `name`, `description`, `project_id`, or `media_type`; changing project_id moves the artifact |
| `DELETE /api/{table}/{id}` | Delete an object; table is groups/projects/artifacts/versions |
| `GET /api/artifacts/{id}/versions` | `{versions: [...]}` ordered by descending version number |
| `GET /api/versions/{id}` | Version details, files, manifest, and metadata |
| `PATCH /api/versions/{id}` | Update `{note?, favorite?}` |
| `GET /api/versions/{id}/file?path=...` | Retrieve a version file; `download=true` forces a download |
| `GET /api/node-package` | Download the custom-node package bundled with the application |

The API accepts `photo` or `video` for `media_type`; the interface displays **Image** and **Video**. Capture updates the type from output files. Group and project names are unique in their respective tables; artifact names are unique within a project.

Moving changes logical ownership while preserving IDs, numbering, and existing physical version paths. Names in archived manifests remain historical capture-time values; current project_name/artifact_name values come from the index.

DELETE removes descendant records and their version files. Confirmation belongs to the interface; the HTTP request itself has no second confirmation step. Empty parent directories may remain. Validation failures generally return 422, missing objects 404, and name/parent conflicts 409.

## Settings and directory operations

| Method and path | Purpose |
| --- | --- |
| `GET /api/settings` | `{repository, docker, browse_root}` |
| `GET /api/directories?path=...` | Directory, parent, and visible subdirectories |
| `POST /api/settings/repository` | `{path}`: open a library or create one in an empty directory |
| `POST /api/repository/backup` | `{path}`: export to a new or empty separate directory |
| `POST /api/repository/import` | `{path}`: validate and replace the active library |

Operation paths must be absolute and accessible to the application. In Docker, `VAULT_HOST_HOME` and `VAULT_HOST_DATA_DIR` map host paths to `/repositories` and `/data`. The current directory picker is designed for directories under the user's home directory.

Export uses the SQLite backup API and copies only indexed version directories. Import checks the database, paths, files, and available hashes before replacement. Libraries are not merged. Import and switching accept a library directory, not a ZIP. Application HTTP operations are serialized; do not modify the active library with external programs.

Appearance, language, font size, tree expansion, and selections are stored in browser localStorage rather than the server API or SQLite.

## On-disk storage

`library.sqlite3` contains settings, groups, projects, artifacts, and versions tables. Directory names use IDs; version.path is relative to the library root. Settings keys of the form `version_counter:ARTIFACT_ID` preserve numbering after a version is deleted.

Version directories contain inputs/outputs, `manifest.json`, `metadata.json`, `prompt.json`, `environment.json`, `README.txt`, and, when available, `workflow.json`. `.incoming/` holds temporary ingestion and deletion operations. `.vault-location` in the initial directory stores the active library's absolute path after switching.

The package schema and SQLite `settings.schema_version` currently both use 1, but represent different format layers. The application adds the supported group_id/media_type fields to earlier libraries. Unsupported schema numbers stop normal operation; back up before updating.

Ingestion writes temporary files, renames the directory, and commits the SQLite index. A crash between filesystem operations and commit can leave an unindexed directory. Inspect its manifest before removing such data. Export includes only indexed versions.
