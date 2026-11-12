import asyncio
from contextlib import closing
import io
import mimetypes
import os
import json
import shutil
import sqlite3
from typing import Literal
from pathlib import Path
import tempfile
import zipfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .store import Store

STATIC = Path(__file__).parent / "static"


class CreateProject(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=20000)
    group_id: str | None = None


class CreateArtifact(CreateProject):
    project_id: str
    media_type: Literal["photo", "video"] = "photo"


class EditDescription(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=20000)
    group_id: str | None = None
    project_id: str | None = None
    media_type: Literal["photo", "video"] | None = None


class PathRequest(BaseModel):
    path: str


class GroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class EditVersion(BaseModel):
    note: str | None = Field(default=None, max_length=20000)
    favorite: bool | None = None


def create_app(data_dir=None):
    application = FastAPI(title="Comfy Vault", docs_url=None, redoc_url=None)
    bootstrap = Path(data_dir or os.environ.get("VAULT_DATA_DIR", str(Path.home() / "ComfyUI_Vault"))).resolve()
    bootstrap.mkdir(parents=True, exist_ok=True)
    location_file = bootstrap / ".vault-location"
    store = Store(location_file.read_text().strip() if location_file.exists() else bootstrap)
    repository_lock = asyncio.Lock()
    application.state.store = store

    @application.middleware("http")
    async def headers(request, call_next):
        async with repository_lock:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; media-src 'self'; "
            "style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'")
        return response

    @application.get("/api/health")
    def health():
        return {"status": "ok", "schema_version": 1}

    @application.get("/api/library")
    def library():
        return {"projects": store.library(), "groups": store.groups()}

    @application.exception_handler(sqlite3.IntegrityError)
    async def conflict(request, error):
        return JSONResponse(status_code=409, content={"detail": "Название уже занято или выбранный родитель не существует / Name conflict or missing parent / 名称冲突或父项不存在"})

    @application.exception_handler(sqlite3.DatabaseError)
    async def invalid_database(request, error):
        return JSONResponse(status_code=422, content={"detail": "Некорректный индекс репозитория / Invalid repository database / 存储库索引无效"})

    @application.exception_handler(ValueError)
    async def invalid_value(request, error):
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @application.exception_handler(OSError)
    async def filesystem_error(request, error):
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @application.post("/api/groups", status_code=201)
    def group(body: GroupRequest):
        return {"id": store.group(body.name)}

    @application.patch("/api/groups/{key}")
    def edit_group(key: str, body: GroupRequest):
        store.update("groups", key, {"name": body.name})
        return {"ok": True}

    @application.delete("/api/{table}/{key}")
    def delete(table: str, key: str):
        store.delete(table, key)
        return {"ok": True}

    def disk_path(value):
        if not value.strip() or not Path(value).expanduser().is_absolute():
            raise HTTPException(422, "Укажите абсолютный путь к каталогу / Enter an absolute directory path / 请输入目录的绝对路径")
        host_home = os.environ.get("VAULT_HOST_HOME")
        host_data = os.environ.get("VAULT_HOST_DATA_DIR")
        if host_data and Path(value) == Path(host_data):
            return bootstrap
        if host_home:
            path = Path(value)
            if path.is_relative_to(host_home):
                return Path("/repositories") / path.relative_to(host_home)
            if path == bootstrap or path.is_relative_to("/repositories"):
                return path
            raise HTTPException(422, "Каталог должен находиться в подключённой домашней папке / Select a mounted home directory / 请选择已挂载的主目录")
        return Path(value).expanduser().resolve()

    def display_path(path):
        path = Path(path)
        if path == bootstrap and os.environ.get("VAULT_HOST_DATA_DIR"):
            return os.environ["VAULT_HOST_DATA_DIR"]
        if path.is_relative_to("/repositories") and os.environ.get("VAULT_HOST_HOME"):
            return str(Path(os.environ["VAULT_HOST_HOME"]) / path.relative_to("/repositories"))
        return str(path)

    @application.get("/api/settings")
    def settings():
        return {"repository": display_path(store.root), "docker": bool(os.environ.get("VAULT_HOST_HOME")),
                "browse_root": os.environ.get("VAULT_HOST_HOME", str(Path.home()))}

    @application.get("/api/directories")
    def directories(path: str):
        directory = disk_path(path).resolve()
        return {"path": display_path(directory), "parent": display_path(directory.parent),
                "directories": [display_path(p) for p in sorted(directory.iterdir()) if p.is_dir() and not p.name.startswith(".")]}

    @application.post("/api/settings/repository")
    def repository(body: PathRequest):
        nonlocal store
        target = disk_path(body.path).resolve()
        if target != store.root and (target.is_relative_to(store.root) or store.root.is_relative_to(target)):
            raise HTTPException(422, "Репозитории не должны быть вложены друг в друга")
        if target.exists() and not (target / "library.sqlite3").exists() and any(target.iterdir()):
            raise HTTPException(422, "Выберите пустой каталог или существующий репозиторий")
        replacement = Store(target)
        location_file.write_text(str(replacement.root))
        store = replacement
        application.state.store = store
        return {"repository": display_path(store.root)}

    @application.post("/api/repository/backup")
    def backup(body: PathRequest):
        return {"path": display_path(store.backup(disk_path(body.path)))}

    @application.post("/api/repository/import")
    def import_repository(body: PathRequest):
        source = disk_path(body.path).resolve()
        if source == store.root or source.is_relative_to(store.root) or store.root.is_relative_to(source):
            raise HTTPException(422, "Источник должен быть отдельным каталогом")
        if not (source / "library.sqlite3").is_file():
            raise HTTPException(422, "В каталоге нет library.sqlite3")
        with tempfile.TemporaryDirectory(prefix="vault-import-") as work:
            stage = Path(work) / "new"
            # Read-only source snapshot: never modify the selected backup.
            stage.mkdir()
            with closing(sqlite3.connect(f"file:{source / 'library.sqlite3'}?mode=ro", uri=True)) as src, closing(sqlite3.connect(stage / "library.sqlite3")) as dst:
                src.backup(dst)
            with closing(sqlite3.connect(stage / "library.sqlite3")) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
                    raise HTTPException(422, "Повреждённый индекс")
                for (relative,) in db.execute("SELECT path FROM versions"):
                    from .store import safe_relative
                    safe_relative(relative)
                    if not relative.startswith("projects/"):
                        raise HTTPException(422, "Недопустимый каталог версии")
                    directory = (source / relative).resolve()
                    if not directory.is_relative_to(source) or any(p.is_symlink() for p in directory.rglob("*")):
                        raise HTTPException(422, "Недопустимый путь или символьная ссылка")
                    shutil.copytree(directory, stage / relative)
            candidate = Store(stage)
            for project in candidate.library():
                for artifact in project["artifacts"]:
                    for version in candidate.versions(artifact["id"]):
                        for file in version["manifest"]["files"]:
                            target = candidate.file(version["id"], file["path"])
                            if file.get("sha256"):
                                import hashlib
                                with target.open("rb") as stream:
                                    if hashlib.file_digest(stream, "sha256").hexdigest() != file["sha256"]:
                                        raise HTTPException(422, "Контрольная сумма не совпала")
            old = Path(work) / "old"
            old.mkdir()
            moved = []
            installed = []
            try:
                for item in store.root.iterdir():
                    if item.name not in {"projects", ".incoming", "library.sqlite3", "library.sqlite3-wal", "library.sqlite3-shm"}:
                        continue
                    shutil.move(str(item), old / item.name)
                    moved.append(item.name)
                for item in stage.iterdir():
                    installed.append(item.name)
                    shutil.move(str(item), store.root / item.name)
            except BaseException:
                for name in installed:
                    item = store.root / name
                    shutil.rmtree(item) if item.is_dir() else item.unlink()
                for name in moved:
                    shutil.move(str(old / name), store.root / name)
                raise
        return {"ok": True}

    @application.get("/api/node-package")
    def node_package():
        package = STATIC.parent.parent / "custom_nodes" / "comfyui_vault"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for source in sorted(package.rglob("*")):
                if (source.is_file() and "__pycache__" not in source.parts and source.suffix != ".pyc"
                        and source.name not in {"comfyui_vault.json", "comfy_vault.json"}):
                    archive.write(source, "comfyui_vault/" + source.relative_to(package).as_posix())
        buffer.seek(0)
        return StreamingResponse(buffer, media_type="application/zip", headers={
            "Content-Disposition": 'attachment; filename="comfyui_vault.zip"'})

    @application.post("/api/projects", status_code=201)
    def project(body: CreateProject):
        return {"id": store.project(body.name, body.description, body.group_id)}

    @application.post("/api/artifacts", status_code=201)
    def artifact(body: CreateArtifact):
        return {"id": store.artifact(body.project_id, body.name, body.description, body.media_type)}

    @application.patch("/api/projects/{record_id}")
    def project_update(record_id: str, body: EditDescription):
        store.update("projects", record_id, body.model_dump(exclude_none=True))
        return {"ok": True}

    @application.patch("/api/artifacts/{record_id}")
    def artifact_update(record_id: str, body: EditDescription):
        store.update("artifacts", record_id, body.model_dump(exclude_none=True))
        return {"ok": True}

    @application.get("/api/artifacts/{record_id}/versions")
    def versions(record_id: str):
        return {"versions": store.versions(record_id)}

    @application.get("/api/versions/{record_id}")
    def detail(record_id: str):
        return store.detail(record_id)

    @application.patch("/api/versions/{record_id}")
    def version_update(record_id: str, body: EditVersion):
        store.update("versions", record_id, body.model_dump(exclude_none=True))
        return {"ok": True}

    @application.get("/api/versions/{record_id}/file")
    def file(record_id: str, path: str, download: bool = False):
        target = store.file(record_id, path)
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        inline = mime in {"image/png", "image/jpeg", "image/webp", "image/gif", "video/mp4", "video/webm", "video/quicktime"}
        record = next(f for f in store.detail(record_id)["files"] if f["path"] == path)
        download_name = Path(record.get("name") or target.name).name
        return FileResponse(target, media_type=mime, filename=download_name,
                            content_disposition_type="inline" if inline and not download else "attachment")

    @application.post("/api/ingest", status_code=201)
    async def ingest(request: Request):
        if request.headers.get("content-type", "").split(";")[0] != "application/zip":
            raise HTTPException(415, "Нужен архив application/zip")
        fd, temp_name = tempfile.mkstemp(suffix=".zip", dir=store.root / ".incoming")
        size = 0
        try:
            with os.fdopen(fd, "wb") as output:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 100 * 1024**3:
                        raise HTTPException(413, "Архив превышает 100 ГБ")
                    output.write(chunk)
            return await asyncio.to_thread(store.ingest, Path(temp_name))
        finally:
            Path(temp_name).unlink(missing_ok=True)

    @application.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    application.mount("/static", StaticFiles(directory=STATIC), name="static")
    return application
