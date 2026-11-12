import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone

from fastapi import HTTPException

from .metadata import describe, json_bytes

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS groups(
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, is_default INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS projects(
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artifacts(
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), name TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, UNIQUE(project_id, name));
CREATE TABLE IF NOT EXISTS versions(
 id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL REFERENCES artifacts(id), number INTEGER NOT NULL,
 capture_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, path TEXT NOT NULL,
 note TEXT NOT NULL DEFAULT '', favorite INTEGER NOT NULL DEFAULT 0,
 UNIQUE(artifact_id, number));
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier():
    return uuid.uuid4().hex


def clean_name(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 160:
        raise HTTPException(422, "Название должно содержать от 1 до 160 символов")
    return value.strip()


def safe_relative(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("Недопустимый путь")
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in ("..", ".", "") for x in value.split("/")) or ":" in value:
        raise ValueError("Недопустимый путь")
    return p


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".incoming").mkdir(exist_ok=True)
        self.db_path = self.root / "library.sqlite3"
        with self.db() as db:
            db.executescript(SCHEMA)
            if "media_type" not in {r[1] for r in db.execute("PRAGMA table_info(artifacts)")}:
                db.execute("ALTER TABLE artifacts ADD COLUMN media_type TEXT NOT NULL DEFAULT 'photo'")
            if "group_id" not in {r[1] for r in db.execute("PRAGMA table_info(projects)")}:
                db.execute("ALTER TABLE projects ADD COLUMN group_id TEXT REFERENCES groups(id)")
                group_id = self.default_group(db)
                db.execute("UPDATE projects SET group_id=?", (group_id,))
            db.execute("INSERT OR IGNORE INTO settings VALUES('schema_version', '1')")
            if db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0] != "1":
                raise RuntimeError("Unsupported library schema; use a compatible application version")

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=60)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def groups(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM groups ORDER BY is_default DESC, name")]

    def default_group(self, db):
        row = db.execute("SELECT id FROM groups WHERE is_default=1").fetchone()
        if row:
            return row[0]
        key = identifier()
        db.execute("INSERT INTO groups VALUES(?,?,1)", (key, "General" if not db.execute("SELECT 1 FROM groups WHERE name='General'").fetchone() else "General " + key[:6]))
        return key

    def group(self, name):
        with self.db() as db:
            key = identifier()
            try:
                db.execute("INSERT INTO groups VALUES(?,?,?)", (key, clean_name(name), int(not db.execute("SELECT 1 FROM groups").fetchone())))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "Группа с таким названием уже существует")
            return key

    def project(self, name, description="", group_id=None):
        name = clean_name(name)
        with self.db() as db:
            project_id = identifier()
            try:
                db.execute("INSERT INTO projects(id,name,description,created_at,group_id) VALUES(?,?,?,?,?)", (project_id, name, description, now(), group_id or self.default_group(db)))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "Проект с таким названием уже существует")
        return project_id

    def artifact(self, project_id, name, description="", media_type="photo"):
        name = clean_name(name)
        with self.db() as db:
            if not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                raise HTTPException(404, "Проект не найден")
            artifact_id = identifier()
            try:
                db.execute("INSERT INTO artifacts(id,project_id,name,description,created_at,media_type) VALUES(?,?,?,?,?,?)", (artifact_id, project_id, name, description, now(), media_type))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "Артефакт с таким названием уже существует")
        return artifact_id

    def library(self):
        with self.db() as db:
            projects = [dict(x) for x in db.execute("SELECT * FROM projects ORDER BY created_at DESC")]
            artifacts = [dict(x) for x in db.execute("""SELECT a.*, count(v.id) version_count,
                max(v.created_at) last_version_at FROM artifacts a LEFT JOIN versions v ON v.artifact_id=a.id
                GROUP BY a.id ORDER BY a.created_at DESC""")]
        for item in artifacts:
            with self.db() as db:
                latest = db.execute("SELECT id FROM versions WHERE artifact_id=? ORDER BY number DESC LIMIT 1", (item["id"],)).fetchone()
            item["latest"] = self.detail(latest[0]) if latest else None
        for project in projects:
            project["artifacts"] = [a for a in artifacts if a["project_id"] == project["id"]]
        return projects

    def update(self, table, key, data):
        allowed = {"groups": {"name"}, "projects": {"name", "description", "group_id"}, "artifacts": {"name", "description", "project_id", "media_type"}, "versions": {"note", "favorite"}}[table]
        fields = {k: v for k, v in data.items() if k in allowed}
        if not fields:
            return
        if "name" in fields:
            fields["name"] = clean_name(fields["name"])
        if "favorite" in fields:
            fields["favorite"] = int(bool(fields["favorite"]))
        with self.db() as db:
            row = db.execute(f"UPDATE {table} SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
                             (*fields.values(), key))
            if row.rowcount != 1:
                raise HTTPException(404, "Запись не найдена")

    def delete(self, table, key):
        if table not in {"groups", "projects", "artifacts", "versions"}:
            raise HTTPException(404, "Не найдено")
        trash = Path(tempfile.mkdtemp(prefix="delete-", dir=self.root / ".incoming"))
        moved = []
        try:
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                if not db.execute(f"SELECT 1 FROM {table} WHERE id=?", (key,)).fetchone():
                    raise HTTPException(404, "Не найдено")
                condition = {"groups": "p.group_id", "projects": "p.id", "artifacts": "a.id", "versions": "v.id"}[table]
                rows = db.execute(f"SELECT v.id,v.path FROM versions v JOIN artifacts a ON a.id=v.artifact_id JOIN projects p ON p.id=a.project_id WHERE {condition}=?", (key,)).fetchall()
                for row in rows:
                    directory = (self.root / row["path"]).resolve()
                    if not directory.is_relative_to(self.root) or directory == self.root:
                        raise HTTPException(422, "Недопустимый путь версии")
                    if directory.exists():
                        target = trash / row["id"]
                        directory.rename(target)
                        moved.append((directory, target))
                    db.execute("DELETE FROM versions WHERE id=?", (row["id"],))
                if table == "groups":
                    db.execute("DELETE FROM artifacts WHERE project_id IN (SELECT id FROM projects WHERE group_id=?)", (key,))
                    db.execute("DELETE FROM projects WHERE group_id=?", (key,))
                elif table == "projects":
                    db.execute("DELETE FROM artifacts WHERE project_id=?", (key,))
                db.execute(f"DELETE FROM {table} WHERE id=?", (key,))
        except BaseException:
            for original, target in reversed(moved):
                target.rename(original)
            raise
        finally:
            shutil.rmtree(trash, ignore_errors=True)

    def backup(self, destination):
        destination = Path(destination).resolve()
        if destination == self.root or destination.is_relative_to(self.root) or self.root.is_relative_to(destination):
            raise HTTPException(422, "Выберите отдельный каталог вне репозитория")
        if destination.exists() and any(destination.iterdir()):
            raise HTTPException(409, "Каталог назначения должен быть пустым")
        destination.mkdir(parents=True, exist_ok=True)
        with self.db() as db, contextlib.closing(sqlite3.connect(destination / "library.sqlite3")) as target:
            db.backup(target)
        # Copy only indexed version directories; no WAL, staging or runtime settings.
        with self.db() as db:
            paths = [r[0] for r in db.execute("SELECT path FROM versions")]
        for relative in paths:
            safe_relative(relative)
            source = (self.root / relative).resolve()
            if not source.is_relative_to(self.root):
                raise HTTPException(422, "Недопустимый путь")
            shutil.copytree(source, destination / relative)
        return str(destination)

    def version_row(self, version_id):
        with self.db() as db:
            row = db.execute("""SELECT v.*, a.name artifact_name, p.name project_name FROM versions v
                JOIN artifacts a ON a.id=v.artifact_id JOIN projects p ON p.id=a.project_id WHERE v.id=?""",
                             (version_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Версия не найдена")
        return dict(row)

    def detail(self, version_id):
        row = self.version_row(version_id)
        directory = self.root / row["path"]
        manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
        metadata = json.loads((directory / "metadata.json").read_text("utf-8"))
        generated = [{"path": name, "role": "metadata", "name": name,
                      "size": (directory / name).stat().st_size} for name in
                     ("workflow.json", "prompt.json", "metadata.json", "environment.json", "manifest.json", "README.txt")
                     if (directory / name).exists()]
        return {**row, "manifest": manifest, "metadata": metadata,
                "files": manifest["files"] + generated}

    def versions(self, artifact_id):
        with self.db() as db:
            ids = [x[0] for x in db.execute("SELECT id FROM versions WHERE artifact_id=? ORDER BY number DESC", (artifact_id,))]
        return [self.detail(x) for x in ids]

    def file(self, version_id, path):
        try:
            safe_relative(path)
        except ValueError:
            raise HTTPException(400, "Недопустимый путь")
        detail = self.detail(version_id)
        if path not in {f["path"] for f in detail["files"]}:
            raise HTTPException(404, "Файл не найден")
        base = (self.root / detail["path"]).resolve()
        target = (base / path).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise HTTPException(404, "Файл не найден")
        return target

    def ingest(self, archive_path):
        staging = Path(tempfile.mkdtemp(prefix="capture-", dir=self.root / ".incoming"))
        final = None
        committed = False
        try:
            with zipfile.ZipFile(archive_path) as archive:
                infos = archive.infolist()
                if len(infos) > 10000 or sum(x.file_size for x in infos) > 100 * 1024**3:
                    raise ValueError("Архив слишком большой")
                names = [x.filename for x in infos]
                if len(names) != len(set(names)) or "capture.json" not in names:
                    raise ValueError("Нужен capture.json; повторяющиеся имена запрещены")
                if archive.getinfo("capture.json").file_size > 32 * 1024**2:
                    raise ValueError("Метаданные слишком большие")
                payload = json.loads(archive.read("capture.json"))
                if payload.get("schema_version") != 1:
                    raise ValueError("Неподдерживаемая версия формата")
                project_name = clean_name(payload.get("project"))
                artifact_name = clean_name(payload.get("artifact"))
                capture_id = str(uuid.UUID(payload["capture_id"]))
                graph = payload.get("prompt")
                if not isinstance(graph, dict) or not graph or any(not isinstance(v, dict) for v in graph.values()):
                    raise ValueError("Нет корректного API workflow")
                files = payload.get("files", [])
                if not files or not any(f.get("role") == "output" for f in files):
                    raise ValueError("Нет файлов результата")
                paths = set()
                for file in files:
                    path = file["path"]
                    safe_relative(path)
                    if file.get("role") not in {"input", "output"} or not path.startswith(file["role"] + "s/"):
                        raise ValueError("Файлы разрешены только в inputs/ и outputs/")
                    if path in paths:
                        raise ValueError("Повторяющийся файл")
                    paths.add(path)
                    if Path(path).suffix.lower() in {".safetensors", ".ckpt", ".gguf", ".pth", ".pt", ".bin", ".onnx"}:
                        raise ValueError("Веса моделей не должны включаться в архив")
                    info = archive.getinfo(path)
                    if (info.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError("Символические ссылки запрещены")
                    target = staging / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    size = 0
                    with archive.open(info) as src, target.open("wb") as dst:
                        while chunk := src.read(1024**2):
                            digest.update(chunk)
                            dst.write(chunk)
                            size += len(chunk)
                    if file.get("sha256") and file["sha256"] != digest.hexdigest():
                        raise ValueError("Контрольная сумма файла не совпала")
                    file["sha256"], file["size"] = digest.hexdigest(), size
                if set(names) != paths | {"capture.json"}:
                    raise ValueError("В архиве есть незаявленные файлы")
            version_id = identifier()
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute("SELECT id FROM versions WHERE capture_id=?", (capture_id,)).fetchone()
                if existing:
                    return {"id": existing[0], "duplicate": True}
                project = db.execute("SELECT id FROM projects WHERE name=?", (project_name,)).fetchone()
                project_id = project[0] if project else identifier()
                if not project:
                    db.execute("INSERT INTO projects(id,name,description,created_at,group_id) VALUES(?,?,?,?,?)", (project_id, project_name, "", now(), self.default_group(db)))
                artifact = db.execute("SELECT id FROM artifacts WHERE project_id=? AND name=?", (project_id, artifact_name)).fetchone()
                artifact_id = artifact[0] if artifact else identifier()
                if not artifact:
                    db.execute("INSERT INTO artifacts(id,project_id,name,description,created_at) VALUES(?,?,?,?,?)", (artifact_id, project_id, artifact_name, "", now()))
                counter_key = "version_counter:" + artifact_id
                counter = db.execute("SELECT value FROM settings WHERE key=?", (counter_key,)).fetchone()
                previous = db.execute("SELECT coalesce(max(number),0) FROM versions WHERE artifact_id=?", (artifact_id,)).fetchone()[0]
                media_type = "video" if any(Path(f["path"]).suffix.lower() in {".mp4", ".webm", ".mov", ".m4v"} for f in files if f["role"] == "output") else "photo"
                db.execute("UPDATE artifacts SET media_type=? WHERE id=?", (media_type, artifact_id))
                number = max(previous, int(counter[0]) if counter else 0) + 1
                db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (counter_key, str(number)))
                created_at = now()
                relative = f"projects/{project_id}/artifacts/{artifact_id}/versions/v{number:06}_{version_id}"
                manifest = {k: v for k, v in payload.items() if k not in {"workflow", "prompt", "environment", "overrides"}}
                manifest.update(id=version_id, number=number, created_at=created_at)
                metadata = describe(graph, payload.get("archive_node_id"), payload.get("overrides"))
                warnings = manifest.setdefault("warnings", [])
                if metadata["unresolved"]:
                    warnings.append("Некоторые параметры вычисляются другими нодами; итоговые значения не захвачены.")
                if not payload.get("workflow"):
                    warnings.append("Визуальный workflow не передан. Доступен только API-граф.")
                for name, data in (("manifest.json", manifest), ("metadata.json", metadata),
                                   ("prompt.json", graph), ("environment.json", payload.get("environment", {}))):
                    (staging / name).write_bytes(json_bytes(data))
                if payload.get("workflow"):
                    (staging / "workflow.json").write_bytes(json_bytes(payload["workflow"]))
                instructions = ["Comfy Vault — ручное восстановление", "", f"Проект: {project_name}",
                                f"Артефакт: {artifact_name}; версия: {number}", "",
                                "1. Установите ComfyUI и custom nodes из environment.json.",
                                "2. Разместите модели из manifest.json по указанным путям. Веса в архив не включены.",
                                "3. Скопируйте каждый input-файл по его comfy_path из manifest.json.",
                                "4. Откройте workflow.json в ComfyUI; проверьте пути, seed и режим fixed.",
                                "5. Для фактических параметров запуска сверяйтесь с prompt.json и metadata.json.",
                                "   Виджет randomize/increment в визуальном workflow может изменить seed при следующем запуске.",
                                "   Если значение вычисляется нодой, его нужно зафиксировать вручную.",
                                "", "Одинаковый seed не гарантирует побитовое совпадение на другом оборудовании или ПО.",
                                "", "Предупреждения:", *warnings]
                (staging / "README.txt").write_text("\n".join(instructions) + "\n", "utf-8")
                final = self.root / relative
                final.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staging, final)
                db.execute("INSERT INTO versions VALUES(?,?,?,?,?,?,?,?)",
                           (version_id, artifact_id, number, capture_id, created_at, relative, "", 0))
            committed = True
            return {"id": version_id, "number": number, "artifact_id": artifact_id, "project_id": project_id, "duplicate": False}
        except (ValueError, KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            raise HTTPException(422, str(exc))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            if final and not committed:
                shutil.rmtree(final, ignore_errors=True)
