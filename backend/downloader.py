from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

import requests

from .catalog import ReceitaCatalog, MUNICIPALITY_UF_NAME, CNAE_HIERARCHY_NAME, EXTERNAL_REFERENCES
from .storage import StorageLibrary

CHUNK_SIZE = 1024 * 1024
MAX_EXTERNAL_BYTES = 5 * 1024 * 1024


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class DownloadManager:
    def __init__(self, data_dir: Path, catalog: ReceitaCatalog, library: StorageLibrary, store=None):
        self.data_dir, self.catalog = data_dir, catalog
        self.library = library
        self.store = store
        self.jobs_dir = data_dir / "controle" / "jobs_download"
        self.competences_dir = data_dir / "competencias"
        self.references_dir = data_dir / "referencias"
        for folder in (self.jobs_dir, self.competences_dir, self.references_dir): folder.mkdir(parents=True, exist_ok=True)
        self._cancel = {}

    def _path(self, job_id): return self.jobs_dir / f"{job_id}.json"

    def _save(self, job):
        job["updated_at"] = now_iso()
        target, temporary = self._path(job["job_id"]), self._path(job["job_id"]).with_suffix(".json.tmp")
        if self.store: self.store.put_operation("download", job["job_id"], job, target)
        for attempt in range(5):
            try:
                temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(target)
                return
            except PermissionError:
                if attempt == 4: raise
                time.sleep(.03 * (attempt + 1))

    def get(self, job_id):
        if self.store:
            stored = self.store.get_operation("download", job_id)
            if stored is not None: return stored
        path = self._path(job_id)
        if not path.exists(): raise KeyError(job_id)
        for attempt in range(8):
            try: return json.loads(path.read_text(encoding="utf-8"))
            except (PermissionError, json.JSONDecodeError):
                if attempt == 7: raise
                time.sleep(.02 * (attempt + 1))

    def list(self):
        if self.store: return self.store.list_operations("download")
        result = []
        for path in self.jobs_dir.glob("*.json"):
            try: result.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError): pass
        return sorted(result, key=lambda j: j.get("created_at", ""), reverse=True)

    def create(self, competence, names, destination_root=None):
        available = {i["name"]: i for i in self.catalog.files(competence)}
        names = list(dict.fromkeys(names))
        invalid = [n for n in names if n not in available]
        if not names: raise ValueError("Selecione pelo menos um arquivo.")
        if invalid: raise ValueError("Arquivos indisponíveis: " + ", ".join(invalid))
        files = [{"name": n, "kind": available[n]["kind"], "size": available[n]["size"],
                  "etag": available[n]["etag"], "status": "pending", "downloaded": 0, "attempts": 0} for n in names]
        job_id = uuid.uuid4().hex[:10]
        destination = self.library.destination(competence, destination_root)
        job = {"job_id": job_id, "competence": competence, "destination": str(destination),
               "status": "queued", "created_at": now_iso(),
               "total_bytes": sum(i["size"] or 0 for i in files), "downloaded_bytes": 0,
               "percent": 0, "current_file": None, "files": files,
               "logs": [f"{now_iso()} - Download criado para {competence}."]}
        self._save(job)
        event = threading.Event(); self._cancel[job_id] = event
        threading.Thread(target=self._run, args=(job_id, event), daemon=True).start()
        return job

    def cancel(self, job_id):
        job = self.get(job_id); self._cancel.setdefault(job_id, threading.Event()).set()
        if job["status"] in {"queued", "running"}:
            job["status"] = "cancelling"; self._log(job, "Cancelamento solicitado; a parte baixada será preservada."); self._save(job)
        elif job["status"] in {"interrupted", "error"}:
            job["status"] = "cancelled"; self._log(job, "Execução encerrada; arquivos parciais foram preservados."); self._save(job)
        return job

    def resume(self, job_id):
        job = self.get(job_id)
        if job["status"] not in {"cancelled", "error", "interrupted"}: raise ValueError("Este download não pode ser retomado.")
        for item in job["files"]:
            if item["status"] not in {"completed", "reused"}: item["status"] = "pending"; item.pop("error", None)
        job["status"] = "queued"; self._log(job, "Download retomado."); self._save(job)
        event = threading.Event(); self._cancel[job_id] = event
        threading.Thread(target=self._run, args=(job_id, event), daemon=True).start()
        return job

    def _log(self, job, message):
        job.setdefault("logs", []).append(f"{now_iso()} - {message}"); job["logs"] = job["logs"][-100:]

    def _target(self, competence, item):
        if item["kind"] == "reference": return self.references_dir / "entrada" / competence / item["name"]
        entry = self.library.get(competence)
        root = Path(entry["path"]) if entry else self.competences_dir / competence
        return root / item["name"]

    def _current_reference(self, name):
        try:
            current = json.loads((self.references_dir / "atual.json").read_text(encoding="utf-8"))
            return current.get("references", {}).get(name, {})
        except (OSError, json.JSONDecodeError):
            return {}

    def local_state(self, competence, item):
        target = self._target(competence, item)
        if target.is_file() and (not item.get("size") or target.stat().st_size == item["size"]):
            return {"status": "same_month", "path": str(target)}
        if item["kind"] == "reference":
            current = self._current_reference(item["name"])
            if current.get("path") and Path(current["path"]).is_file():
                reusable = (item["name"] in EXTERNAL_REFERENCES or bool(
                    item.get("etag") and current.get("etag") == item["etag"]
                    and item.get("size") == current.get("size")))
                return {"status": "reusable" if reusable else "shared_reference",
                        "source_competence": current.get("source_competence")}
        return {"status": "remote"}

    def _run(self, job_id, cancel):
        job = self.get(job_id); job["status"] = "running"; self._save(job)
        try:
            for item in job["files"]:
                if item["status"] in {"completed", "reused"}: continue
                if cancel.is_set(): raise InterruptedError
                job["current_file"] = item["name"]; item["status"] = "downloading"; self._save(job)
                self._download_retried(job, item, cancel)
            job["status"] = "completed"; job["current_file"] = None; self._log(job, "Download concluído.")
        except InterruptedError:
            job["status"] = "cancelled"; self._log(job, "Download interrompido com segurança.")
        except Exception as exc:
            job["status"] = "error"; self._log(job, f"Falha: {exc}")
        finally:
            self._recalculate(job); self._save(job); self._cancel.pop(job_id, None)

    def _download_retried(self, job, item, cancel):
        error = None
        for attempt in range(1, 4):
            item["attempts"] = attempt
            try: self._download_one(job, item, cancel); return
            except InterruptedError: raise
            except Exception as exc:
                error = exc; item["error"] = str(exc); self._log(job, f"Tentativa {attempt}/3 falhou em {item['name']}: {exc}"); self._save(job)
                if attempt < 3: time.sleep(attempt * 2)
        item["status"] = "error"; raise RuntimeError(f"Falha definitiva em {item['name']}: {error}")

    def _download_one(self, job, item, cancel):
        target = self._target(job["competence"], item); target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and (not item["size"] or target.stat().st_size == item["size"]):
            self._validate_file(target, item["name"]); item["downloaded"] = target.stat().st_size; item["status"] = "reused"
            if item["kind"] == "reference": self._version_reference(job, item, target)
            self._log(job, f"Arquivo existente reutilizado: {item['name']}."); return
        if item["kind"] == "reference":
            current = self._current_reference(item["name"])
            previous = Path(current["path"]) if current.get("path") else None
            reusable = (item["name"] in EXTERNAL_REFERENCES or
                        bool(item.get("etag") and current.get("etag") == item["etag"]
                             and item.get("size") == current.get("size")))
            if reusable and previous and previous.is_file() and (
                    item["size"] is None or previous.stat().st_size == item["size"]):
                shutil.copy2(previous, target)
                self._validate_file(target, item["name"])
                item.update(status="reused", downloaded=target.stat().st_size)
                self._version_reference(job, item, target)
                self._log(job, f"Referência idêntica no catálogo; versão local reutilizada: {item['name']}.")
                return
        part = target.with_suffix(target.suffix + ".part"); offset = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        external = item["name"] in EXTERNAL_REFERENCES
        url = EXTERNAL_REFERENCES[item["name"]] if external else self.catalog.url_for(f"{job['competence']}/{item['name']}")
        if external:
            headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
            if item["name"] == MUNICIPALITY_UF_NAME:
                headers["Referer"] = "https://www.gov.br/receitafederal/dados/municipios.csv/view"
        with requests.get(url, auth=None if external else self.catalog.auth,
                          headers=headers, stream=True, timeout=(30, 120)) as response:
            response.raise_for_status(); append = offset > 0 and response.status_code == 206
            if offset and not append: offset = 0
            with part.open("ab" if append else "wb") as output:
                for chunk in response.iter_content(CHUNK_SIZE):
                    if cancel.is_set(): raise InterruptedError
                    if chunk:
                        output.write(chunk)
                        if external and output.tell() > MAX_EXTERNAL_BYTES:
                            raise ValueError("Referência externa excede o limite de 5 MB.")
                        item["downloaded"] = output.tell()
                        self._recalculate(job); self._save(job)
        actual = part.stat().st_size
        if item["size"] and actual != item["size"]: raise IOError(f"tamanho {actual} difere do catálogo {item['size']}")
        self._validate_file(part, item["name"]); part.replace(target); item.update(status="completed", downloaded=actual, completed_at=now_iso()); item.pop("error", None)
        if item["kind"] == "reference": self._version_reference(job, item, target)
        self._log(job, f"Arquivo validado: {item['name']}."); self._save(job)

    @staticmethod
    def _validate_zip(path):
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad: raise zipfile.BadZipFile(f"conteúdo corrompido: {bad}")

    @staticmethod
    def _validate_file(path, name):
        if name == MUNICIPALITY_UF_NAME:
            import csv
            with path.open(encoding="latin1", newline="") as source:
                rows = csv.reader(source, delimiter=";")
                header = next(rows, [])
                if len(header) != 5 or header[-1].strip().upper() != "UF":
                    raise ValueError("Complemento municipal da Receita com formato inesperado.")
                valid = sum(len(row) == 5 and row[0].strip().isdigit() and len(row[4].strip()) == 2 for row in rows)
                if valid < 5000:
                    raise ValueError("Complemento municipal da Receita incompleto.")
        elif name == CNAE_HIERARCHY_NAME:
            from .cnae_hierarchy import load_cnae_hierarchy
            with zipfile.ZipFile(path) as archive:
                if sum(member.file_size for member in archive.infolist()) > 20 * 1024 * 1024:
                    raise ValueError("Planilha CNAE 2.3 excede o limite de conteúdo.")
            if len(load_cnae_hierarchy(path)) < 1300:
                raise ValueError("Planilha CNAE 2.3 incompleta.")
        else:
            DownloadManager._validate_zip(path)

    def _version_reference(self, job, item, source):
        digest = hashlib.sha256()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""): digest.update(chunk)
        sha = digest.hexdigest(); version = self.references_dir / "versoes" / sha / item["name"]; version.parent.mkdir(parents=True, exist_ok=True)
        if not version.exists(): shutil.copy2(source, version)
        item["sha256"] = sha; current_path = self.references_dir / "atual.json"
        try: current = json.loads(current_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): current = {"references": {}}
        current.setdefault("references", {})[item["name"]] = {"sha256": sha, "path": str(version), "source_competence": job["competence"], "etag": item.get("etag"), "size": source.stat().st_size, "updated_at": now_iso()}
        temp = current_path.with_suffix(".json.tmp"); temp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"); temp.replace(current_path)

    @staticmethod
    def _recalculate(job):
        job["downloaded_bytes"] = sum(int(i.get("downloaded") or 0) for i in job["files"]); total = int(job.get("total_bytes") or 0)
        job["percent"] = round(job["downloaded_bytes"] * 100 / total, 2) if total else 0

    def storage(self):
        usage = shutil.disk_usage(self.data_dir)
        return {"data_dir": str(self.data_dir), "total": usage.total, "used": usage.used, "free": usage.free}
