from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class ProjectManager:
    """Persiste projetos e vincula artefatos existentes sem duplicar arquivos."""

    def __init__(self, data_dir: Path, library, processor, geocoder, store=None):
        self.path = data_dir / "controle" / "projetos.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.library = library
        self.processor = processor
        self.geocoder = geocoder
        self.store = store
        self._lock = threading.RLock()

    def _load(self):
        if self.store:
            stored = self.store.get_document("project_state", "global")
            if stored is not None: return stored
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "projects": [], "ignored_keys": []}

    def _save(self, state):
        if self.store: self.store.put_document("project_state", "global", state, self.path)
        temp = self.path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    @staticmethod
    def _natural_key(process):
        return "|".join((process.get("competence", ""), process.get("uf", ""),
                         process.get("municipality_code", ""), str(process.get("active_only", True))))

    def _discover(self, state, processes):
        state.setdefault("ignored_keys", [])
        existing_keys = {p.get("natural_key") for p in state["projects"] if not p.get("duplicate_of")}
        existing_keys.update(state["ignored_keys"])
        processes = sorted(processes, key=lambda p: p.get("updated_at", p.get("created_at", "")), reverse=True)
        for process in processes:
            if process.get("status") != "completed":
                continue
            key = self._natural_key(process)
            if key in existing_keys:
                continue
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
            created = process.get("created_at") or now_iso()
            state["projects"].append({
                "project_id": digest, "natural_key": key,
                "name": f"{process.get('municipality_name', 'Projeto').title()} — {process.get('competence')}",
                "competence": process.get("competence"), "uf": process.get("uf"),
                "municipality_code": process.get("municipality_code"),
                "municipality_name": process.get("municipality_name"),
                "active_only": process.get("active_only", True),
                "process_job_id": process.get("job_id"), "created_at": created,
                "updated_at": process.get("updated_at", created), "origin": "automatic",
            })
            existing_keys.add(key)

    def _enrich(self, project, readiness, processes, geocodings):
        result = dict(project)
        ready = set(readiness.get("ready_competences", []))
        month = next((item for item in readiness.get("competences", []) if item["competence"] == project.get("competence")), None)
        local_data_ready = bool(month and month.get("present", 0) > 0 and readiness.get("references_complete"))
        shared_data_ready = bool(readiness.get("references_complete") and any(item.get("present", 0) > 0 for item in readiness.get("competences", [])))
        process = next((p for p in processes if p.get("job_id") == project.get("process_job_id")), None)
        explicit_geocoding = project.get("geocoding_job_id")
        geocodings = [g for g in geocodings if
                      (explicit_geocoding and g.get("job_id") == explicit_geocoding) or
                      (not explicit_geocoding and project.get("origin") == "automatic" and g.get("process_job_id") == project.get("process_job_id"))]
        geocoding = max(geocodings, key=lambda g: g.get("updated_at", g.get("created_at", "")), default=None)
        steps = {
            "data": {"status": "completed" if project.get("competence") in ready or local_data_ready else "pending", "label": "Dados oficiais"},
            "preparation": {"status": "completed" if process and process.get("status") == "completed" else (process or {}).get("status", "available" if shared_data_ready else "pending"), "label": "Base municipal"},
            "geocoding": {"status": (geocoding or {}).get("status", "available" if process and process.get("status") == "completed" else "pending"), "label": "Geocodificação"},
            "review": {"status": "available" if geocoding and geocoding.get("map_url") else "locked", "label": "Mapa e revisão"},
        }
        coverage = {"is_partial": bool((process or {}).get("is_partial")),
                    "parts_used": len((process or {}).get("source_files", [])),
                    "parts_official": (process or {}).get("official_file_count"),
                    "missing_parts": (process or {}).get("missing_source_files", []),
                    "acknowledged_at": (process or {}).get("incomplete_acknowledged_at")}
        processing_seconds = (process or {}).get("processing_seconds")
        if processing_seconds is None and process and process.get("status") == "completed":
            try:
                processing_seconds = max(0, (datetime.fromisoformat(process["updated_at"]) -
                                             datetime.fromisoformat(process["created_at"])).total_seconds())
            except (KeyError, ValueError):
                pass
        result.update(steps=steps, rows=(process or {}).get("rows_found", 0), coverage=coverage,
                      processing_seconds=processing_seconds,
                      geocoding_job_id=(geocoding or {}).get("job_id"),
                      map_url=(geocoding or {}).get("map_url"), map_summary=(geocoding or {}).get("map_summary"),
                      next_url=(geocoding or {}).get("map_url") or "/etapas")
        return result

    def list(self):
        with self._lock:
            state = self._load(); before = len(state["projects"])
            processes = self.processor.list()
            self._discover(state, processes)
            if len(state["projects"]) != before: self._save(state)
            readiness = self.processor.readiness()
            geocodings = self.geocoder.list()
            return [self._enrich(p, readiness, processes, geocodings)
                    for p in sorted(state["projects"], key=lambda p: p.get("updated_at", ""), reverse=True)]

    def get(self, project_id):
        project = next((p for p in self.list() if p["project_id"] == project_id), None)
        if not project: raise KeyError(project_id)
        return project

    def duplicate(self, project_id):
        with self._lock:
            source = self.get(project_id); state = self._load(); copy = {k: v for k, v in source.items() if k not in {"steps", "rows", "map_url", "map_summary", "next_url", "geocoding_job_id"}}
            copy.update(project_id=uuid.uuid4().hex[:10], name=f"{source['name']} — cópia", duplicate_of=project_id,
                        origin="duplicate", created_at=now_iso(), updated_at=now_iso())
            state["projects"].append(copy); self._save(state)
            return self.get(copy["project_id"])

    def create(self, name, competence=None):
        name = (name or "").strip()
        if not name: raise ValueError("Informe um nome para o projeto.")
        with self._lock:
            state = self._load(); project_id = uuid.uuid4().hex[:10]
            project = {"project_id": project_id, "name": name, "competence": competence,
                       "created_at": now_iso(), "updated_at": now_iso(), "origin": "manual"}
            state["projects"].append(project); self._save(state)
            return self.get(project_id)

    def select_competence(self, project_id, competence):
        readiness = self.processor.readiness()
        month = next((item for item in readiness.get("competences", []) if item["competence"] == competence), None)
        if not month or month.get("present", 0) < 1:
            raise ValueError("Baixe ao menos uma parte de Estabelecimentos deste mês antes de avançar.")
        if not readiness.get("references_complete"):
            raise ValueError("Baixe também as tabelas auxiliares da Receita antes de avançar.")
        with self._lock:
            state = self._load()
            project = next((p for p in state["projects"] if p.get("project_id") == project_id), None)
            if not project: raise KeyError(project_id)
            if project.get("process_job_id") and project.get("competence") != competence:
                raise ValueError("Este projeto já tem uma base municipal de outro mês.")
            project.update(competence=competence, updated_at=now_iso())
            self._save(state)
            return self.get(project_id)

    def rename(self, project_id, name):
        name = (name or "").strip()
        if not name: raise ValueError("Informe um nome para o projeto.")
        with self._lock:
            state = self._load(); project = next((p for p in state["projects"] if p.get("project_id") == project_id), None)
            if not project: raise KeyError(project_id)
            project.update(name=name, updated_at=now_iso()); self._save(state)
            return self.get(project_id)

    def attach_process(self, project_id, process):
        if not project_id: return
        with self._lock:
            state = self._load(); project = next((p for p in state["projects"] if p.get("project_id") == project_id), None)
            if not project: raise KeyError(project_id)
            project.update(process_job_id=process["job_id"], geocoding_job_id=None, competence=process.get("competence"), uf=process.get("uf"),
                           municipality_code=process.get("municipality_code"), municipality_name=process.get("municipality_name"),
                           active_only=process.get("active_only", True), process_output_format=process.get("output_format", "csv"), updated_at=now_iso())
            project["natural_key"] = self._natural_key(project); self._save(state)

    def attach_geocoding(self, project_id, geocoding):
        if not project_id: return
        with self._lock:
            state = self._load(); project = next((p for p in state["projects"] if p.get("project_id") == project_id), None)
            if not project: raise KeyError(project_id)
            if project.get("process_job_id") != geocoding.get("process_job_id"):
                raise ValueError("A geocodificação não pertence à base municipal deste projeto.")
            project.update(geocoding_job_id=geocoding["job_id"], updated_at=now_iso()); self._save(state)

    def reuse_matches(self, competence, uf, municipality_code, active_only=True, output_format="csv"):
        processes = [p for p in self.processor.list() if p.get("status") == "completed"
                     and p.get("competence") == competence and p.get("uf") == uf
                     and str(p.get("municipality_code")) == str(municipality_code)
                     and bool(p.get("active_only", True)) == bool(active_only)
                     and p.get("output_format", "csv") == output_format]
        library = getattr(self.processor, "library", None)
        folder = library.path(competence) if library else None
        local_files = {path.name for path in folder.glob("Estabelecimentos*.zip")} if folder else set()
        processes = [p for p in processes if not p.get("is_partial") or set(p.get("source_files", [])) == local_files]
        projects = self.list()
        results = []
        for process in sorted(processes, key=lambda p: p.get("updated_at", ""), reverse=True):
            geocodings = [g for g in self.geocoder.list() if g.get("status") == "completed"
                          and g.get("process_job_id") == process.get("job_id")]
            geocodings.sort(key=lambda g: g.get("updated_at", g.get("created_at", "")), reverse=True)
            owners = [{"project_id": p["project_id"], "name": p["name"]} for p in projects
                      if p.get("process_job_id") == process.get("job_id")]
            results.append({
                "stage": "geocoded" if geocodings else "prepared",
                "process": {k: process.get(k) for k in ("job_id", "competence", "uf", "municipality_code",
                            "municipality_name", "active_only", "output_format", "rows_found", "updated_at",
                            "is_partial", "source_files", "official_file_count", "missing_source_files")},
                "geocodings": [{"job_id": g.get("job_id"), "output_format": g.get("output_format"),
                                 "resolve_ties": g.get("resolve_ties"), "map_url": g.get("map_url"),
                                 "download_url": g.get("download_url"), "map_summary": g.get("map_summary"),
                                 "updated_at": g.get("updated_at")} for g in geocodings],
                "projects": owners,
            })
        return results

    def reviews(self, project_id):
        self.get(project_id)
        path = self.path.parent / "revisoes" / f"{project_id}.json"
        if self.store:
            stored = self.store.get_document("review", project_id)
            if stored is not None: return stored
        try: return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return {"project_id": project_id, "records": {}}

    def set_review(self, project_id, cnpj, reviewed, note=""):
        cnpj = "".join(ch for ch in str(cnpj).upper() if ch.isalnum())
        if not cnpj: raise ValueError("CNPJ inválido.")
        with self._lock:
            state = self.reviews(project_id); state["records"][cnpj] = {"reviewed": bool(reviewed), "note": (note or "").strip(), "updated_at": now_iso()}
            folder = self.path.parent / "revisoes"; folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"{project_id}.json"; temp = target.with_suffix(".json.tmp")
            if self.store: self.store.put_document("review", project_id, state, target)
            temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"); temp.replace(target)
            return state["records"][cnpj]

    def remove(self, project_id):
        with self._lock:
            state = self._load(); original = len(state["projects"])
            removed = next((p for p in state["projects"] if p.get("project_id") == project_id), None)
            state["projects"] = [p for p in state["projects"] if p.get("project_id") != project_id]
            if len(state["projects"]) == original: raise KeyError(project_id)
            if removed and not removed.get("duplicate_of") and removed.get("natural_key"):
                state.setdefault("ignored_keys", []).append(removed["natural_key"])
            self._save(state)
            return {"removed": project_id, "files_preserved": True}
