"""Create reproducible source/node ZIPs in a caller-selected destination."""
import argparse
import fnmatch
from pathlib import Path
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument("destination", type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
args.destination.mkdir(parents=True, exist_ok=True)


def package(destination, sources, prefix):
    count = 0
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for source, relative in sources:
            if not source.is_file() or "__pycache__" in source.parts or source.suffix == ".pyc":
                continue
            info = zipfile.ZipInfo(prefix + relative.as_posix(), (2026, 11, 11, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if source.suffix == ".command" else 0o100644) << 16
            archive.writestr(info, source.read_bytes())
            count += 1
    print(f"{destination.name}: {count} files, {destination.stat().st_size} bytes")


# Keep release archives free of the same local state excluded from Git.
excluded_directories = {".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
                        ".mypy_cache", ".ruff_cache", "htmlcov", ".idea", ".vscode",
                        ".codex", ".agents", ".aws", ".ssh", "data", "ComfyUI_Vault",
                        "projects", ".incoming", "backups", "artifacts", "build", "dist"}
excluded_files = {".DS_Store", "Thumbs.db", "Desktop.ini", ".vault-location",
                  "comfyui_vault.json", "comfy_vault.json"}
excluded_patterns = ("*.py[cod]", "*.zip", "*.log", "*.sqlite*", "*.db", "*.db-wal", "*.db-shm",
                     "*.safetensors", "*.ckpt", "*.gguf", "*.pth", "*.pt", "*.bin", "*.onnx",
                     "*.pem", "*.key", "._*", "*.swp", "*.swo", "*~", ".coverage*")


def distributable(source):
    relative = source.relative_to(root)
    return (source.is_file() and not source.is_symlink()
            and not source.resolve().is_relative_to(args.destination.resolve())
            and not any(part in excluded_directories for part in relative.parts[:-1])
            and source.name not in excluded_files
            and not (source.name.startswith(".env") and source.name != ".env.example")
            and not any(fnmatch.fnmatch(source.name, pattern) for pattern in excluded_patterns))


sources = [(source, source.relative_to(root)) for source in sorted(root.rglob("*")) if distributable(source)]
package(args.destination / "comfy-vault.zip", sources, "comfy-vault/")
node = root / "custom_nodes/comfyui_vault"
package(args.destination / "comfyui_vault.zip",
        [(source, source.relative_to(node)) for source in sorted(node.rglob("*"))
         if distributable(source)], "comfyui_vault/")
