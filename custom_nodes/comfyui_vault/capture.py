"""File-only capture helpers; no models are loaded or copied."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import subprocess
import urllib.parse
import uuid
import zipfile

WEIGHTS = {".safetensors", ".ckpt", ".gguf", ".pth", ".pt", ".bin", ".onnx"}
MODEL_FIELDS = {
    "ckpt_name": "checkpoints", "unet_name": "diffusion_models", "diffusion_model": "diffusion_models",
    "lora_name": "loras", "vae_name": "vae", "clip_name": "text_encoders",
    "clip_name1": "text_encoders", "clip_name2": "text_encoders", "clip_name3": "text_encoders",
    "control_net_name": "controlnet", "clip_vision": "clip_vision", "clip_vision_name": "clip_vision",
    "style_model_name": "style_models", "upscale_model_name": "upscale_models", "model_name": None,
}
FILE_FIELDS = {"image", "video", "audio", "mask", "file", "filename", "file_path", "image_path", "video_path"}
DIRECTORIES = {"unet": "diffusion_models", "clip": "text_encoders"}
_hashes = {}


def config():
    defaults = {"url": "http://127.0.0.1:8088", "hash_models": True, "timeout": 600, "extra_input_roots": []}
    path = Path(__file__).parent / "comfyui_vault.json"
    if not path.exists():
        # Preserve a previously configured URL when the package folder is renamed.
        path = Path(__file__).parent / "comfy_vault.json"
    if path.exists():
        defaults.update(json.loads(path.read_text("utf-8")))
    defaults["url"] = os.environ.get("COMFY_VAULT_URL", defaults["url"]).rstrip("/")
    return defaults


def linked(value, graph):
    return (isinstance(value, list) and len(value) == 2 and str(value[0]) in graph
            and isinstance(value[1], int))


def branch(graph, root):
    stack, seen = [str(root)], set()
    while stack:
        key = stack.pop()
        if key in seen or key not in graph:
            continue
        seen.add(key)
        stack.extend(str(v[0]) for v in graph[key].get("inputs", {}).values() if linked(v, graph))
    return seen


def snapshot_prompt(prompt):
    """Copy the API graph without ComfyUI's execution-cache fingerprints.

    ComfyUI adds is_changed to node records during execution; it may contain
    NaN to force re-execution. It is not an input or a generation parameter.
    Keep the live graph untouched so its cache behavior remains unchanged.
    """
    return {node_id: {key: value for key, value in node.items() if key != "is_changed"}
            for node_id, node in prompt.items()}


def sha256(path, cache=False):
    path = Path(path)
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    if cache and key in _hashes:
        return _hashes[key]
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024**2):
            digest.update(chunk)
    if cache:
        _hashes[key] = digest.hexdigest()
    return digest.hexdigest()


def git_state(path):
    try:
        def run(*args):
            return subprocess.check_output(["git", "-C", str(path), *args], stderr=subprocess.DEVNULL, timeout=8).decode().strip()
        # A child directory inside ComfyUI's repo is not its own custom-node repo.
        root = Path(run("rev-parse", "--show-toplevel")).resolve()
        if root != Path(path).resolve():
            return {"commit": None, "dirty": None}
        result = {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain"))}
        try:
            remote = run("remote", "get-url", "origin")
            parsed = urllib.parse.urlsplit(remote)
            if parsed.scheme in {"https", "http", "ssh"} and parsed.hostname:
                result["repository"] = urllib.parse.urlunsplit((parsed.scheme, parsed.hostname, parsed.path, "", ""))
            elif remote.startswith("git@") and ":" in remote:
                result["repository"] = "https://" + remote[4:].replace(":", "/", 1)
        except subprocess.SubprocessError:
            pass
        return result
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def environment(folder_paths, graph, used):
    root = Path(folder_paths.base_path)
    env = {"python": platform.python_version(), "platform": platform.platform(), "comfyui": git_state(root),
           "custom_nodes": [], "node_types": sorted({graph[k].get("class_type", "?") for k in used}),
           "packages": {}}
    try:
        import importlib.metadata
        env["packages"] = {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()
                           if dist.metadata["Name"]}
    except ImportError:
        pass
    try:
        import comfyui_version
        env["comfyui"]["version"] = comfyui_version.__version__
    except (ImportError, AttributeError):
        pass
    try:
        import torch
        env["torch_runtime"] = {"cuda": torch.version.cuda, "mps_available": torch.backends.mps.is_available(),
                                "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "MPS/CPU"}
    except (ImportError, AttributeError, RuntimeError):
        pass
    # Registry modules identify which custom-node packages the saved branch uses.
    try:
        import nodes
        import inspect
        packages = set()
        for node_id in used:
            cls = nodes.NODE_CLASS_MAPPINGS.get(graph[node_id].get("class_type"))
            if cls is None:
                continue
            source = Path(inspect.getfile(cls)).resolve()
            for custom_root in folder_paths.get_folder_paths("custom_nodes"):
                custom_root = Path(custom_root).resolve()
                if source.is_relative_to(custom_root):
                    first = source.relative_to(custom_root).parts[0]
                    packages.add(custom_root / first)
        for package in sorted(packages):
            record = {"name": package.name, **git_state(package if package.is_dir() else package.parent)}
            if package.is_file():
                record["source_sha256"] = sha256(package)
            env["custom_nodes"].append(record)
    except (ImportError, TypeError, OSError, ValueError):
        env["custom_nodes_warning"] = "Не удалось полностью определить пакеты custom nodes."
    return env


def resolve_input(value, folder_paths, settings):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        try:
            path = Path(folder_paths.get_annotated_filepath(value)).resolve()
        except (AttributeError, ValueError):
            path = Path(value).resolve()
        roots = [Path(folder_paths.get_input_directory()), Path(folder_paths.get_output_directory()),
                 Path(folder_paths.get_temp_directory()), *map(Path, settings["extra_input_roots"])]
        if path.suffix.lower() in WEIGHTS or not path.is_file():
            return None
        if not any(path.is_relative_to(root.resolve()) for root in roots):
            return None
    except (OSError, ValueError, RuntimeError):
        # Workflow strings can be prompts, not paths. Probing them may fail with
        # ENAMETOOLONG, embedded NULs, inaccessible files or symlink loops.
        return None
    return path


def collect(graph, archive_id, folder_paths, settings):
    graph = {str(k): v for k, v in graph.items()}
    used = branch(graph, archive_id)
    refs, models, warnings = [], [], []
    model_categories = [k for k in folder_paths.folder_names_and_paths
                        if k not in {"custom_nodes", "configs", "input", "output", "temp"}]
    seen_refs, seen_models = set(), set()
    for node_id in sorted(used):
        node = graph[node_id]
        kind = node.get("class_type", "?")
        # Archive file inputs are outputs, not source references.
        if kind.startswith("ComfyVault"):
            continue
        for key, value in node.get("inputs", {}).items():
            if not isinstance(value, str):
                if key in FILE_FIELDS and linked(value, graph):
                    warnings.append(f"#{node_id} {kind}.{key}: имя входного файла вычисляется; автоматическая копия не гарантируется.")
                if key in MODEL_FIELDS and linked(value, graph):
                    warnings.append(f"#{node_id} {kind}.{key}: имя модели вычисляется; проверьте зависимость вручную.")
                continue
            suffix = Path(value).suffix.lower()
            if key in MODEL_FIELDS or suffix in WEIGHTS:
                expected = MODEL_FIELDS.get(key)
                # UpscaleModelLoader uses model_name, as do many extension loaders.
                if kind == "UpscaleModelLoader" and key == "model_name":
                    expected = "upscale_models"
                candidates = [expected] if expected else []
                if expected == "text_encoders":
                    candidates.append("clip")
                if expected == "diffusion_models":
                    candidates.append("unet")
                candidates.extend(k for k in model_categories if k not in candidates)
                found = []
                for category in candidates:
                    try:
                        full = folder_paths.get_full_path(category, value)
                        if full and Path(full).is_file():
                            found.append((category, Path(full)))
                            if expected and category in candidates[:2]:
                                break
                    except (KeyError, ValueError, OSError):
                        pass
                if not found:
                    models.append({"name": value, "category": expected, "node_id": node_id,
                                   "input": key, "comfy_path": f"models/{expected}/{value}" if expected else None,
                                   "sha256": None, "resolved": False})
                    warnings.append(f"#{node_id} {kind}.{key}: файл модели не найден или его путь требует проверки: {value}")
                    continue
                if len(found) > 1:
                    warnings.append(f"#{node_id} {kind}.{key}: найдено несколько возможных каталогов модели; проверьте путь.")
                category, full = found[0]
                category = DIRECTORIES.get(category, category)
                marker = (node_id, key, str(full))
                if marker in seen_models:
                    continue
                seen_models.add(marker)
                models.append({"name": value, "category": category, "node_id": node_id, "input": key,
                               "comfy_path": f"models/{category}/{value.replace(chr(92), '/')}",
                               "size": full.stat().st_size, "sha256": sha256(full, cache=True) if settings["hash_models"] else None,
                               "resolved": True})
            elif key in FILE_FIELDS or key.endswith(("_path", "_file")) or resolve_input(value, folder_paths, settings):
                full = resolve_input(value, folder_paths, settings)
                if full:
                    marker = (node_id, key)
                    if marker in seen_refs:
                        continue
                    seen_refs.add(marker)
                    relative = None
                    for directory, label in ((folder_paths.get_input_directory(), "input"),
                                             (folder_paths.get_output_directory(), "output"),
                                             (folder_paths.get_temp_directory(), "temp")):
                        if full.is_relative_to(Path(directory).resolve()):
                            relative = label + "/" + full.relative_to(Path(directory).resolve()).as_posix()
                            break
                    refs.append({"source": full, "node_id": node_id, "input": key, "source_value": value,
                                 "comfy_path": relative, "name": full.name})
                    if relative is None:
                        warnings.append(f"#{node_id}: исходный файл вне стандартных каталогов; назначьте путь вручную: {value}")
                elif value.strip() and (kind.startswith(("Load", "VHS_Load")) or key.endswith(("_path", "_file"))):
                    warnings.append(f"#{node_id} {kind}.{key}: входной файл не скопирован: {value}")
    if not models:
        warnings.append("Автоматически распознанных моделей нет. Проверьте ноды загрузки в workflow.")
    return refs, models, list(dict.fromkeys(warnings)), used


def send_archive(path, settings):
    url = urllib.parse.urlsplit(settings["url"])
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
        raise ValueError("Некорректный адрес Comfy Vault")
    connection_cls = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    connection = connection_cls(url.hostname, url.port, timeout=settings["timeout"])
    try:
        connection.putrequest("POST", url.path.rstrip("/") + "/api/ingest")
        connection.putheader("Content-Type", "application/zip")
        connection.putheader("Content-Length", str(Path(path).stat().st_size))
        connection.endheaders()
        with Path(path).open("rb") as source:
            while chunk := source.read(1024**2):
                connection.send(chunk)
        response = connection.getresponse()
        body = response.read(1024**2)
        if response.status not in (200, 201):
            raise RuntimeError(f"Comfy Vault вернул HTTP {response.status}: {body.decode('utf-8', 'replace')[:1000]}")
        return json.loads(body)
    finally:
        connection.close()


def build_archive(path, payload, files):
    """Snapshot bytes and hash the same bytes (ZIP_STORED avoids recompressing video)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
        descriptors = []
        for index, item in enumerate(files):
            source, role = Path(item["source"]), item["role"]
            if source.suffix.lower() in WEIGHTS:
                raise ValueError("Копирование весов моделей запрещено")
            relative = f"{role}s/{index:04}_{source.name}"
            before = source.stat()
            digest = hashlib.sha256()
            with source.open("rb") as src, archive.open(relative, "w", force_zip64=True) as dst:
                while chunk := src.read(1024**2):
                    dst.write(chunk)
                    digest.update(chunk)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError(f"Файл изменился во время архивирования: {source.name}")
            descriptor = {k: v for k, v in item.items() if k != "source"}
            descriptor.update(path=relative, sha256=digest.hexdigest(), size=after.st_size)
            descriptors.append(descriptor)
        payload["files"] = descriptors
        archive.writestr("capture.json", json.dumps(payload, ensure_ascii=False, allow_nan=False))


def capture(project, artifact, prompt, workflow, archive_id, output_files, metadata, folder_paths, scratch):
    settings = config()
    if not project.strip() or not artifact.strip():
        raise ValueError("Укажите названия проекта и артефакта")
    prompt = snapshot_prompt(prompt)
    refs, models, warnings, used = collect(prompt, archive_id, folder_paths, settings)
    env = environment(folder_paths, prompt, used)
    if env["comfyui"]["dirty"]:
        warnings.append("В ComfyUI есть незакоммиченные изменения; одного commit для восстановления недостаточно.")
    for package in env["custom_nodes"]:
        if package["commit"] is None or package["dirty"]:
            warnings.append(f"Custom node {package['name']}: точная версия кода не закреплена; сохраните установленный пакет отдельно.")
    payload = {"schema_version": 1, "capture_id": str(uuid.uuid4()), "project": project.strip(),
               "artifact": artifact.strip(), "prompt": prompt, "workflow": workflow,
               "archive_node_id": str(archive_id), "models": models, "warnings": warnings,
               "overrides": metadata or {}, "environment": env,
               "input_capture": "Files copied at archive-node execution; do not change source files during a queued run."}
    archive = Path(scratch) / "capture.zip"
    files = [{**r, "role": "input"} for r in refs] + [{**f, "role": "output"} for f in output_files]
    build_archive(archive, payload, files)
    result = send_archive(archive, settings)
    return result, settings["url"] + "/?version=" + result["id"]
