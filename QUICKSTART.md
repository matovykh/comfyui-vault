# User guide

[← README](README.md)

## Requirements and first launch

The primary supported setup is macOS with Docker Desktop and a local ComfyUI installation. The container needs neither a GPU nor models. The first build requires internet access; an existing image only needs local connectivity between ComfyUI and the application.

1. Install and start Docker Desktop.
2. Download or clone the project, then open a terminal in the directory containing `compose.yaml`.
3. Run:

   ```bash
   mkdir -p "$HOME/ComfyUI_Vault"
   docker compose up -d --build
   ```

4. Open [http://127.0.0.1:8088](http://127.0.0.1:8088).

All library data is stored in `$HOME/ComfyUI_Vault` by default: `/Users/yourname/ComfyUI_Vault` on macOS. Docker Desktop must have access to mounted directories. Keep the application source directory separate from your library; do not use a nonempty source checkout as a new library.

On macOS, `bash ./start.command` starts the application and opens the browser. Stop it with `docker compose down`. Stopping the container does not delete the library.

### Choose another initial directory

Copy `.env.example` to `.env`, uncomment `VAULT_DATA_DIR`, and set an absolute path:

```dotenv
VAULT_DATA_DIR="/Users/yourname/Pictures/ComfyUI_Vault"
```

Run `docker compose up -d --build`. `.env` overrides the default location. If you previously switched libraries through Settings, `.vault-location` in the initial directory determines the active library on subsequent launches.

## Install the custom nodes

Copy `custom_nodes/comfyui_vault` into your ComfyUI installation's `custom_nodes` directory. Alternatively, use **Connect ComfyUI** to download the package, then extract its folder there.

```text
ComfyUI/
  custom_nodes/
    comfyui_vault/
      __init__.py
      nodes.py
      capture.py
```

Avoid an extra nesting level. If the old `comfy_vault` package is installed, replace it rather than loading two copies of the same nodes. Restart ComfyUI completely after installation.

**Archive Images**, **Archive Files**, and **Capture Value** appear under **Comfy Vault**. The default server address is `http://127.0.0.1:8088`. See [node configuration](custom_nodes/comfyui_vault/README.md) for a different setup.

## Save your first version

1. Connect the final `IMAGE` to Archive Images. If Save Image has no output, use the same image supplied to Save Image.
2. Enter `project` and `artifact`, for example `Characters` and `Main character`.
3. Run the workflow and wait for archiving to succeed.
4. Click **Refresh** in the application. The project and artifact appear automatically.
5. Open the version and review its outputs, references, seeds, sampler parameters, models, and paths.

One archive-node execution creates one version containing the entire IMAGE batch. Repeating Queue creates another version even if the graph is unchanged. Multiple archive nodes can save different artifacts.

For video, connect `VHS_FILENAMES` to Archive Files. When using `files`, provide paths and connect the saving node's output to `after`. A node's visual position does not control execution order.

## Organize your library

The sidebar tree follows **Group → Project → Artifact**. Expand buttons do not change the selection. Tree state and selection are saved in the browser. On first use, General is expanded to show its projects.

- `+` beside Library creates a group.
- `+` beside a group creates a project in that group.
- `+` beside a project creates an artifact in that project.
- Selecting a group opens its management page and project list.
- Selecting a project opens its artifacts and the selected artifact's history.

Groups have a name and can be deleted. Projects and artifacts have names and descriptions, and can be deleted or moved. The artifact type, **Image / Video**, can be set in its form and is updated from captured output files. Moving preserves version files and IDs.

Project names are unique across the library because archive nodes identify a project by name rather than by group. Artifact names are unique within a project. After renaming or moving an artifact into another project, update the names in your workflow.

General can be renamed. If a generation arrives in an empty library, the application creates the default group and required objects.

### Select an artifact

The selector header shows a name and a single-line description. Each expanded row shows the latest preview, type, name, and description. Long descriptions are shortened with an ellipsis; hover to read the full text. An artifact without its own description uses the project description.

Clicking a row or its preview selects the artifact and loads its history. Artifacts with no generations show a placeholder.

## Browse versions and media

Click a preview to open the media viewer with its version number. Click elsewhere on the card to open version details. Favorite and Delete buttons perform only their own action.

The viewer supports navigation, video controls, fitting media to the window, a 1:1 view, and opening the original. Navigation follows search, sorting, and **Show favorites**. Multiple outputs in one version are included in the same navigation list.

Version details include files, parameters, models and paths, environment information, the source workflow, and a note. Favorites and notes are saved in the library.

### Delete objects

Deleting a version removes its files. Deleting an artifact, project, or group removes all descendant versions and their files. The confirmation dialog explains the consequences and focuses **Cancel**. Enter cancels the operation. Deletion is permanent; deleted version numbers are not reused.

## Interface settings

Open **Settings** at the bottom of the sidebar.

| Setting | Behavior |
| --- | --- |
| Appearance | Three-way switch: sun for Light, monitor for System, moon for Dark |
| Language | English, Russian, or Chinese; user content is not translated |
| Font size | Base size from 12 to 22 px, applied immediately to all application text; Reset restores 16 px |

Appearance and language are also available at the top right. All three preferences are saved in the current browser and can be different on another device. No browser extension is required.

## Library directory, export, and import

The active directory appears under **Local storage**. Settings can open another library or create one in an empty directory. Switching leaves previous data where it was. The new library cannot contain the current one or be nested inside it.

Compose mounts your home directory at `/repositories`; the interface displays paths as they appear on the host computer. Directory selection is limited to that mapping. External drives require another bind mount and corresponding path-mapping changes in `app/main.py`.

**Export:** choose a new or empty destination and click **Export**. The application creates a consistent SQLite snapshot and copies indexed versions. Temporary operations and the active-library selection file are not included.

**Import:** select a directory containing `library.sqlite3` and version files, then confirm replacement. The application checks the database, paths, file availability, and available SHA-256 hashes. Validation failure leaves the current library unchanged. Import replaces the current library rather than merging it; export the current library first.

### Transfer a library manually

1. Finish all generations and uploads, then stop the container.
2. Copy the entire active directory, including `library.sqlite3` and any remaining SQLite journals.
3. On the new computer, use that directory as `VAULT_DATA_DIR` or open it through Settings.
4. Start the application. Numbering, descriptions, favorites, and notes continue from that library.

Do not copy only `projects/`: the index and user metadata are in SQLite. If you copy the initial directory with `.vault-location`, remember that the file contains the old absolute path. Export is a simpler way to obtain a portable copy of the active library.

## Restore a generation in ComfyUI

Install the dependencies listed under **Models and paths** and **Environment**, place reference files at their `comfy_path` locations, and open `workflow.json`. Check seeds against `prompt.json` and change randomize/increment to fixed. For computed parameters, use Capture Value records and fix values manually where necessary.

The application does not install models, modify ComfyUI, or run generations. Bit-identical output on different hardware is not guaranteed.

## Troubleshooting

```bash
docker compose ps
docker compose logs --tail=80
curl --fail http://127.0.0.1:8088/api/health
```

The health endpoint returns `{"status":"ok","schema_version":1}`. Use HTTP and port 8088; this is separate from ComfyUI's usual port 8188.

| Problem | What to check |
| --- | --- |
| The page does not open | Docker Desktop readiness, port conflicts, and container logs |
| Nodes are missing | Installation path, duplicate packages, and a full ComfyUI restart |
| An archive node cannot reach the server | URL and connectivity from the ComfyUI process; localhost inside a container refers to that container |
| Dependencies are missing | Version warnings, computed paths, and custom loader nodes |
| An update still shows the old interface | Rebuild with `docker compose up -d --build`, then reload with ⌘⇧R |
| Directory access fails | Permissions, Docker Desktop File sharing, and whether the directory is mounted |

Before sharing an issue report, remove credentials, private paths, and other sensitive data from workflows, logs, and configuration. Review library contents before publishing them.
