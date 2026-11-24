from __future__ import annotations

import json
import hashlib
import shutil
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from send2trash import send2trash


ACTIVE_STATES = {"queued", "running", "uploading", "cancelling"}
TERMINAL_STATES = {"completed", "cancelled", "error", "interrupted"}
ALLOWED_TRANSITIONS = {
    "queued": {"running", "uploading", "cancelled", "cancelling", "error", "interrupted"},
    "running": {"completed", "cancelled", "cancelling", "error", "interrupted"},
    "uploading": {"running", "completed", "cancelled", "error", "interrupted"},
    "cancelling": {"cancelled", "error", "interrupted"},
    "interrupted": {"queued", "running", "cancelled", "error"},
    "error": {"queued", "running", "cancelled"},
    "cancelled": {"queued", "running"},
    "completed": set(),
}


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class OperationalStore:
    """SQLite control plane. Large artifacts remain on disk; JSON files are compatibility mirrors."""

    SCHEMA_VERSION = 2

    def __init__(self, data_dir: Path, executor_id: str | None = None, lease_seconds: int = 45):
        self.data_dir = data_dir.resolve()
        self.control_dir = self.data_dir / "controle"
        self.control_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.control_dir / "geocnpj.sqlite3"
        self.executor_id = executor_id or str(uuid.uuid4())
        self.lease_seconds = lease_seconds
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self):
        with closing(self._connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    kind TEXT NOT NULL, document_id TEXT NOT NULL, payload TEXT NOT NULL,
                    source_path TEXT, updated_at TEXT NOT NULL,
                    PRIMARY KEY(kind, document_id)
                );
                CREATE TABLE IF NOT EXISTS operations (
                    kind TEXT NOT NULL, operation_id TEXT NOT NULL, status TEXT NOT NULL,
                    percent REAL NOT NULL DEFAULT 0, heartbeat_at TEXT NOT NULL,
                    created_at TEXT, error TEXT, payload TEXT NOT NULL,
                    PRIMARY KEY(kind, operation_id)
                );
                CREATE INDEX IF NOT EXISTS operations_status_idx ON operations(status, heartbeat_at);
                CREATE TABLE IF NOT EXISTS transition_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, operation_id TEXT NOT NULL,
                    from_status TEXT, to_status TEXT NOT NULL, changed_at TEXT NOT NULL, reason TEXT
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(operations)")}
            if "executor_id" not in columns: db.execute("ALTER TABLE operations ADD COLUMN executor_id TEXT")
            if "lease_until" not in columns: db.execute("ALTER TABLE operations ADD COLUMN lease_until TEXT")
            db.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                       (self.SCHEMA_VERSION, now_iso()))

    def _lease_until(self):
        return (datetime.now().astimezone() + timedelta(seconds=self.lease_seconds)).isoformat(timespec="seconds")

    @staticmethod
    def _json(payload):
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def put_document(self, kind: str, document_id: str, payload: dict, source_path: Path | None = None):
        stamp = payload.get("updated_at") or now_iso()
        with self._lock, closing(self._connect()) as db, db:
            db.execute("""INSERT INTO documents(kind, document_id, payload, source_path, updated_at)
                VALUES (?, ?, ?, ?, ?) ON CONFLICT(kind, document_id) DO UPDATE SET
                payload=excluded.payload, source_path=excluded.source_path, updated_at=excluded.updated_at""",
                       (kind, document_id, self._json(payload), str(source_path) if source_path else None, stamp))

    def get_document(self, kind: str, document_id: str) -> dict | None:
        with closing(self._connect()) as db, db:
            row = db.execute("SELECT payload FROM documents WHERE kind=? AND document_id=?", (kind, document_id)).fetchone()
        return json.loads(row["payload"]) if row else None

    def put_operation(self, kind: str, operation_id: str, payload: dict, source_path: Path | None = None,
                      reason: str | None = None, validate_transition: bool = False):
        status = payload.get("status", "queued")
        stamp = payload.get("updated_at") or now_iso()
        with self._lock, closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT status, executor_id, lease_until FROM operations WHERE kind=? AND operation_id=?",
                                  (kind, operation_id)).fetchone()
            old_status = previous["status"] if previous else None
            if status in ACTIVE_STATES and previous and previous["executor_id"] not in (None, self.executor_id):
                if previous["lease_until"] and previous["lease_until"] > now_iso():
                    raise RuntimeError("Esta execução já está ativa em outra instância do GeoCNPJ.")
            if validate_transition and old_status and status != old_status and status not in ALLOWED_TRANSITIONS.get(old_status, set()):
                raise ValueError(f"Transição operacional inválida: {old_status} → {status}.")
            owner = self.executor_id if status in ACTIVE_STATES else None
            lease_until = self._lease_until() if owner else None
            db.execute("""INSERT INTO operations(kind, operation_id, status, percent, heartbeat_at, created_at, error, payload, executor_id, lease_until)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(kind, operation_id) DO UPDATE SET
                status=excluded.status, percent=excluded.percent, heartbeat_at=excluded.heartbeat_at,
                error=excluded.error, payload=excluded.payload, executor_id=excluded.executor_id,
                lease_until=excluded.lease_until""",
                       (kind, operation_id, status, float(payload.get("percent") or 0), stamp,
                        payload.get("created_at"), payload.get("error") or (payload.get("message") if status == "error" else None),
                        self._json(payload), owner, lease_until))
            if old_status != status:
                db.execute("INSERT INTO transition_log(kind, operation_id, from_status, to_status, changed_at, reason) VALUES (?, ?, ?, ?, ?, ?)",
                           (kind, operation_id, old_status, status, stamp, reason))
            if source_path:
                db.execute("""INSERT INTO documents(kind, document_id, payload, source_path, updated_at)
                    VALUES (?, ?, ?, ?, ?) ON CONFLICT(kind, document_id) DO UPDATE SET
                    payload=excluded.payload, source_path=excluded.source_path, updated_at=excluded.updated_at""",
                           (kind, operation_id, self._json(payload), str(source_path), stamp))

    def get_operation(self, kind: str, operation_id: str) -> dict | None:
        with closing(self._connect()) as db, db:
            row = db.execute("SELECT payload, executor_id, lease_until, heartbeat_at FROM operations WHERE kind=? AND operation_id=?", (kind, operation_id)).fetchone()
        if not row: return None
        payload = json.loads(row["payload"])
        payload["_execution"] = {"executor_id": row["executor_id"], "lease_until": row["lease_until"],
                                 "heartbeat_at": row["heartbeat_at"]}
        return payload

    def list_operations(self, kind: str | None = None) -> list[dict]:
        query, values = "SELECT payload, executor_id, lease_until, heartbeat_at FROM operations", ()
        if kind:
            query += " WHERE kind=?"; values = (kind,)
        query += " ORDER BY COALESCE(created_at, heartbeat_at) DESC"
        with closing(self._connect()) as db, db:
            rows = db.execute(query, values).fetchall()
        result = []
        for row in rows:
            payload = json.loads(row["payload"])
            payload["_execution"] = {"executor_id": row["executor_id"], "lease_until": row["lease_until"],
                                     "heartbeat_at": row["heartbeat_at"]}
            result.append(payload)
        return result

    @staticmethod
    def _read_json(path: Path):
        try: return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return None

    @staticmethod
    def _backup(path: Path):
        backup = path.with_suffix(path.suffix + ".pre-sqlite.bak")
        if path.exists() and not backup.exists():
            shutil.copy2(path, backup)

    def migrate_json_controls(self) -> dict:
        marker = self.get_document("migration", "json_v1")
        if marker:
            return marker
        imported = {"projects": 0, "library": 0, "reviews": 0, "operations": 0}
        for filename, kind, document_id in (("projetos.json", "project_state", "global"),
                                             ("biblioteca.json", "library_state", "global")):
            path = self.control_dir / filename; payload = self._read_json(path)
            if payload is not None:
                self._backup(path); self.put_document(kind, document_id, payload, path); imported["projects" if kind == "project_state" else "library"] += 1
        review_dir = self.control_dir / "revisoes"
        for path in review_dir.glob("*.json") if review_dir.exists() else []:
            payload = self._read_json(path)
            if payload is not None:
                self._backup(path); self.put_document("review", path.stem, payload, path); imported["reviews"] += 1
        patterns = [
            ("download", self.control_dir / "jobs_download", "*.json", "job_id"),
            ("validation", self.control_dir / "validacoes", "*.json", "validation_id"),
            ("process", self.data_dir / "processamentos", "*/status.json", "job_id"),
            ("geocoding", self.data_dir / "geocodificacoes", "*/status.json", "job_id"),
        ]
        for kind, folder, pattern, id_key in patterns:
            for path in folder.glob(pattern) if folder.exists() else []:
                payload = self._read_json(path); operation_id = (payload or {}).get(id_key)
                if payload is not None and operation_id:
                    self._backup(path); self.put_operation(kind, operation_id, payload, path, reason="Migração do controle JSON")
                    imported["operations"] += 1
        result = {**imported, "completed_at": now_iso(), "schema_version": self.SCHEMA_VERSION}
        self.put_document("migration", "json_v1", result)
        return result

    def mark_abandoned(self) -> list[dict]:
        changed = []
        with self._lock, closing(self._connect()) as db, db:
            rows = db.execute("""SELECT kind, operation_id, payload, status FROM operations
                WHERE status IN ('queued','running','uploading','cancelling')
                AND (lease_until IS NULL OR lease_until < ?)""", (now_iso(),)).fetchall()
        for row in rows:
            payload = json.loads(row["payload"]); previous = payload.get("status")
            payload.update(status="interrupted", interrupted_from=previous, interrupted_at=now_iso(),
                           message="Execução interrompida por encerramento ou reinicialização da aplicação.", updated_at=now_iso())
            self.put_operation(row["kind"], row["operation_id"], payload, reason="Processo anterior não está mais ativo")
            changed.append({"kind": row["kind"], "operation_id": row["operation_id"], "previous_status": previous})
        return changed

    def renew_owned_leases(self):
        stamp, lease = now_iso(), self._lease_until()
        with self._lock, closing(self._connect()) as db, db:
            cursor = db.execute("""UPDATE operations SET heartbeat_at=?, lease_until=?
                WHERE executor_id=? AND status IN ('queued','running','uploading','cancelling')""",
                                (stamp, lease, self.executor_id))
        return cursor.rowcount

    def owned_active(self):
        with closing(self._connect()) as db, db:
            rows = db.execute("""SELECT kind, operation_id FROM operations WHERE executor_id=?
                AND status IN ('queued','running','uploading','cancelling')""", (self.executor_id,)).fetchall()
        return [dict(row) for row in rows]

    def interrupt_owned(self):
        changed = []
        for row in self.owned_active():
            payload = self.get_operation(row["kind"], row["operation_id"]) or {}
            payload.update(status="interrupted", interrupted_from=payload.get("status"), interrupted_at=now_iso(),
                           message="Execução interrompida pelo encerramento controlado da aplicação.", updated_at=now_iso())
            self.put_operation(row["kind"], row["operation_id"], payload, reason="Encerramento controlado")
            changed.append(row)
        return changed

    def remove_completed_artifact(self, kind: str, operation_id: str, projects: list[dict]) -> dict:
        if kind not in {"process", "geocoding"} or not operation_id or Path(operation_id).name != operation_id:
            raise ValueError("Artefato inválido para exclusão.")
        root = self.data_dir / ("processamentos" if kind == "process" else "geocodificacoes")
        path = (root / operation_id).resolve()
        if path.parent != root.resolve() or path.is_symlink():
            raise ValueError("Caminho do artefato inválido para exclusão.")
        with self._lock:
            operation = self.get_operation(kind, operation_id)
            if operation is None: raise KeyError(operation_id)
            if operation.get("status") in ACTIVE_STATES:
                raise ValueError("Há uma execução em andamento. Interrompa-a antes de excluir.")
            if kind == "process":
                if any(p.get("process_job_id") == operation_id for p in projects):
                    raise ValueError("Esta base está vinculada a um projeto. Remova o vínculo antes de excluí-la.")
                if any(g.get("process_job_id") == operation_id for g in self.list_operations("geocoding")):
                    raise ValueError("Exclua primeiro as geocodificações geradas a partir desta base.")
            else:
                if any(p.get("geocoding_job_id") == operation_id or
                       (p.get("origin") == "automatic" and p.get("process_job_id") == operation.get("process_job_id"))
                       for p in projects):
                    raise ValueError("Esta geocodificação está vinculada a um projeto. Remova o vínculo antes de excluí-la.")
            had_files = path.exists()
            if had_files: send2trash(str(path))
            with closing(self._connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM operations WHERE kind=? AND operation_id=?", (kind, operation_id))
                db.execute("DELETE FROM documents WHERE kind=? AND document_id=?", (kind, operation_id))
                db.execute("INSERT INTO transition_log(kind, operation_id, from_status, to_status, changed_at, reason) VALUES (?, ?, ?, ?, ?, ?)",
                           (kind, operation_id, operation.get("status"), "removed", now_iso(), "Exclusão pelo Acervo"))
            return {"ok": True, "kind": kind, "job_id": operation_id, "files_sent_to_trash": had_files}

    def recoverable(self) -> list[dict]:
        with closing(self._connect()) as db, db:
            rows = db.execute("SELECT kind, operation_id, status, percent, heartbeat_at, error, payload FROM operations WHERE status IN ('interrupted','error','cancelled') ORDER BY heartbeat_at DESC").fetchall()
        result = []
        for row in rows:
            payload = json.loads(row["payload"])
            result.append({"kind": row["kind"], "operation_id": row["operation_id"], "status": row["status"],
                           "percent": row["percent"], "updated_at": row["heartbeat_at"], "error": row["error"],
                           "competence": payload.get("competence"), "message": payload.get("message") or (payload.get("logs") or [""])[-1],
                           "current_file": payload.get("current_file"), "payload": payload})
        return result

    def diagnostics(self) -> dict:
        with closing(self._connect()) as db, db:
            version = db.execute("SELECT MAX(version) version FROM schema_migrations").fetchone()["version"]
            counts = {row["kind"]: row["total"] for row in db.execute("SELECT kind, COUNT(*) total FROM operations GROUP BY kind")}
        return {"database": str(self.path), "schema_version": version, "executor_id": self.executor_id,
                "lease_seconds": self.lease_seconds, "operation_counts": counts,
                "recoverable": len(self.recoverable())}

    @staticmethod
    def _path_size(path: Path) -> tuple[int, int]:
        if not path.exists(): return 0, 0
        if path.is_file():
            try: return path.stat().st_size, 1
            except OSError: return 0, 0
        size = count = 0
        for item in path.rglob("*"):
            try:
                if item.is_file() and not item.is_symlink(): size += item.stat().st_size; count += 1
            except OSError: pass
        return size, count

    @staticmethod
    def _orphan_id(issue: str, kind: str, path: Path) -> str:
        return hashlib.sha1(f"{issue}|{kind}|{path.resolve()}".encode("utf-8")).hexdigest()[:12]

    def scan_orphans(self, projects: list[dict], include_ignored=False) -> dict:
        ignored_state = self.get_document("orphan_ignore", "global") or {"ids": {}}
        ignored = ignored_state.get("ids", {})
        rows = []

        def add(issue, kind, path, title, detail, actions, **metadata):
            path = path.resolve(); orphan_id = self._orphan_id(issue, kind, path)
            if not include_ignored and orphan_id in ignored: return
            size, file_count = self._path_size(path)
            rows.append({"orphan_id": orphan_id, "issue": issue, "kind": kind, "path": str(path),
                         "title": title, "detail": detail, "size": size, "file_count": file_count,
                         "actions": actions, "ignored": orphan_id in ignored, **metadata})

        project_processes = {p.get("process_job_id") for p in projects if p.get("process_job_id")}
        project_geocodings = {p.get("geocoding_job_id") for p in projects if p.get("geocoding_job_id")}
        definitions = (("process", self.data_dir / "processamentos", project_processes),
                       ("geocoding", self.data_dir / "geocodificacoes", project_geocodings))
        kind_names = {"process": "Base municipal", "geocoding": "Geocodificação"}
        for kind, root, linked_ids in definitions:
            known = {item.get("job_id") for item in self.list_operations(kind)}
            if root.exists():
                for folder in root.iterdir():
                    if not folder.is_dir(): continue
                    status_path = folder / "status.json"; job_id = folder.name
                    payload = self._read_json(status_path)
                    if job_id not in known:
                        add("unregistered", kind, folder, f"{kind_names[kind]} não registrada: {job_id}",
                            "A pasta possui estado legível, mas não está registrada no SQLite." if payload else "A pasta não possui um status.json válido.",
                            ["register", "ignore", "trash"] if payload else ["ignore", "trash"], job_id=job_id)
                        continue
                    operation = self.get_operation(kind, job_id) or {}
                    if operation.get("status") == "completed" and job_id not in linked_ids:
                        add("unlinked", kind, folder, f"{kind_names[kind]} sem projeto: {job_id}",
                            "O resultado está registrado e íntegro, mas nenhum projeto aponta para ele.",
                            ["ignore", "trash"], job_id=job_id, process_job_id=operation.get("process_job_id"))
                    partials = folder / "partials"
                    if operation.get("status") == "completed" and partials.exists() and any(partials.iterdir()):
                        add("redundant_temporary", kind, partials, f"Parciais concluídas: {job_id}",
                            "A saída final já foi gerada; estes arquivos intermediários não são mais necessários.",
                            ["ignore", "trash"], job_id=job_id)
            for operation in self.list_operations(kind):
                job_id = operation.get("job_id")
                if job_id and not (root / job_id).exists():
                    add("missing", kind, root / job_id, f"Arquivo ausente: {job_id}",
                        "A execução está registrada no SQLite, mas sua pasta não existe no disco.", ["ignore"], job_id=job_id)

        active_downloads = any(item.get("status") in ACTIVE_STATES for item in self.list_operations("download"))
        temporary_roots = [self.data_dir / "competencias", self.data_dir / "referencias" / "entrada", self.control_dir]
        for root in temporary_roots:
            if not root.exists(): continue
            for path in root.rglob("*"):
                if not path.is_file() or path.name.endswith(".pre-sqlite.bak"): continue
                if (path.suffix.lower() == ".part" and not active_downloads) or path.name.endswith(".json.tmp"):
                    add("temporary", "file", path, f"Temporário abandonado: {path.name}",
                        "Arquivo parcial sem execução ativa associada.", ["ignore", "trash"])

        counts = {}
        for row in rows: counts[row["issue"]] = counts.get(row["issue"], 0) + 1
        return {"ok": not rows, "total": len(rows), "counts": counts, "items": sorted(rows, key=lambda r: (r["issue"], -r["size"])),
                "ignored_count": len(ignored), "scanned_at": now_iso()}

    def handle_orphan(self, orphan_id: str, action: str, projects: list[dict]) -> dict:
        scan = self.scan_orphans(projects, include_ignored=True)
        item = next((row for row in scan["items"] if row["orphan_id"] == orphan_id), None)
        if not item: raise KeyError(orphan_id)
        if action not in item["actions"]: raise ValueError("Esta ação não é permitida para o artefato.")
        if action == "ignore":
            state = self.get_document("orphan_ignore", "global") or {"ids": {}}
            state.setdefault("ids", {})[orphan_id] = {"path": item["path"], "issue": item["issue"], "ignored_at": now_iso()}
            self.put_document("orphan_ignore", "global", state)
            return {"ok": True, "action": action, "item": item}
        path = Path(item["path"]).resolve()
        if action == "register":
            status = self._read_json(path / "status.json")
            id_key = "job_id"
            if not status or not status.get(id_key): raise ValueError("O status do artefato não é válido para registro.")
            self.put_operation(item["kind"], status[id_key], status, path / "status.json", reason="Artefato órfão registrado manualmente")
            return {"ok": True, "action": action, "item": item}
        if action == "trash":
            try: path.relative_to(self.data_dir)
            except ValueError as exc: raise ValueError("Somente artefatos dentro da pasta gerenciada podem ser enviados à Lixeira.") from exc
            if path in {self.data_dir, self.control_dir} or not path.exists(): raise ValueError("Destino de exclusão recusado por segurança.")
            send2trash(str(path))
            return {"ok": True, "action": action, "item": item, "recoverable": True}
        raise ValueError("Ação inválida.")
