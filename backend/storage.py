from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from send2trash import send2trash


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class StorageLibrary:
    def __init__(self, data_dir: Path, store=None):
        self.data_dir = data_dir.resolve()
        self.store = store
        self.control_dir = self.data_dir / "controle"
        self.registry_path = self.control_dir / "biblioteca.json"
        self.control_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if self.store:
            stored = self.store.get_document("library_state", "global")
            if stored is not None: return stored
        try: return json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return {"locations": {}}

    def _save(self, data: dict):
        if self.store: self.store.put_document("library_state", "global", data, self.registry_path)
        temporary = self.registry_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.registry_path)

    def register(self, competence: str, folder: Path, origin: str, managed: bool) -> dict:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", competence):
            raise ValueError("Mês inválido. Use o formato AAAA-MM.")
        folder = folder.resolve()
        folder.mkdir(parents=True, exist_ok=True)
        data = self._load()
        previous = data.get("locations", {}).get(competence)
        if previous and Path(previous["path"]).resolve() != folder:
            raise ValueError("Este mês já aponta para outra pasta. Remova o vínculo atual antes de trocar o local.")
        if previous and previous.get("managed") and not managed:
            return previous
        if previous and not previous.get("managed") and managed:
            raise ValueError("Esta pasta está vinculada como externa. Remova o vínculo antes de usá-la como destino gerenciado.")
        entry = {"competence": competence, "path": str(folder), "origin": origin,
                 "managed": bool(managed), "registered_at": now_iso()}
        data.setdefault("locations", {})[competence] = entry
        self._save(data)
        return entry

    def get(self, competence: str) -> dict | None:
        return self._load().get("locations", {}).get(competence)

    def path(self, competence: str) -> Path | None:
        entry = self.get(competence)
        return Path(entry["path"]) if entry else None

    def ensure_legacy(self):
        root = self.data_dir / "competencias"
        if not root.exists(): return
        for folder in root.iterdir():
            if folder.is_dir() and not self.get(folder.name):
                self.register(folder.name, folder, "download", True)

    def inventory(self, validated: set[str] | None = None) -> list[dict]:
        self.ensure_legacy(); validated = validated or set(); result = []
        for competence, entry in self._load().get("locations", {}).items():
            folder = Path(entry["path"]); files = list(folder.glob("*.zip")) if folder.exists() else []
            size = sum(path.stat().st_size for path in files if path.is_file())
            file_details = [{"name": path.name, "size": path.stat().st_size,
                             "removable": bool(re.fullmatch(r"Estabelecimentos\d+\.zip", path.name, re.IGNORECASE))}
                            for path in sorted(files, key=lambda item: item.name) if path.is_file()]
            result.append({**entry, "exists": folder.exists(), "file_count": len(files), "size": size,
                           "validated": competence in validated, "files": file_details})
        return sorted(result, key=lambda item: item["competence"], reverse=True)

    def references_inventory(self) -> dict:
        """Read-only inventory of downloaded official references and the CNEFE cache."""
        root = self.data_dir / "referencias"
        try:
            current = json.loads((root / "atual.json").read_text(encoding="utf-8")).get("references", {})
        except (OSError, ValueError, TypeError):
            current = {}
        descriptions = {
            "Cnaes.zip": "Códigos e descrições das atividades econômicas da base CNPJ.",
            "Municipios.zip": "Nomes e códigos de municípios usados pela Receita.",
            "Motivos.zip": "Motivos da situação cadastral.",
            "Paises.zip": "Nomes e códigos de países do cadastro.",
            "MunicipiosUF.csv": "Complemento ao CNPJ: relaciona o código de município com a UF.",
            "CNAE_Subclasses_2_3_Estrutura_Detalhada.xlsx": "IBGE/Concla: acrescenta seção, divisão e grupo à atividade CNAE.",
        }
        rows = []
        for name, description in descriptions.items():
            meta = current.get(name) or {}
            path = Path(meta["path"]) if meta.get("path") else None
            present = bool(path and path.is_file() and not path.is_symlink()
                           and path.name == name and root.resolve() in path.resolve().parents)
            versions = list((root / "versoes").glob(f"*/{name}"))
            rows.append({"name": name, "description": description, "present": present,
                         "size": path.stat().st_size if present else 0,
                         "path": str(path) if path else None,
                         "source_competence": meta.get("source_competence"),
                         "updated_at": meta.get("updated_at"),
                         "sha256": meta.get("sha256"), "version_count": sum(p.is_file() for p in versions)})
        hierarchy_meta = current.get("CNAE_Subclasses_2_3_Estrutura_Detalhada.xlsx") or {}
        hierarchy = Path(hierarchy_meta["path"]) if hierarchy_meta.get("path") else None
        folder_size, folder_files = self._folder_size(root)
        cache = Path(os.getenv("GEOCNPJ_GEO_RUNTIME_DIR", str(self.data_dir / "geo_runtime"))) / "cache"
        cache_size, cache_files = self._folder_size(cache)
        return {"files": rows, "stored_size": folder_size, "stored_file_count": folder_files,
                "hierarchy": {"present": bool(hierarchy and hierarchy.is_file()),
                              "path": str(hierarchy) if hierarchy else None,
                              "size": hierarchy.stat().st_size if hierarchy and hierarchy.is_file() else 0},
                "geocoding_cache": {"path": str(cache), "size": cache_size, "file_count": cache_files}}

    def remove_downloaded_file(self, competence: str, filename: str) -> dict:
        entry = self.get(competence)
        if not entry: raise KeyError(competence)
        if not entry.get("managed"):
            raise ValueError("Arquivos de pastas externas não podem ser excluídos pelo GeoCNPJ; remova apenas o vínculo.")
        if not re.fullmatch(r"Estabelecimentos\d+\.zip", filename, re.IGNORECASE):
            raise ValueError("Somente partes de Estabelecimentos gerenciadas podem ser excluídas aqui.")
        folder = Path(entry["path"]).resolve()
        path = folder / filename
        if path.is_symlink() or path.resolve().parent != folder or not path.is_file():
            raise ValueError("Arquivo não encontrado ou fora da pasta registrada.")
        send2trash(str(path))
        return {"ok": True, "message": f"{filename} enviado à Lixeira.", "competence": competence}

    def downloaded_file_path(self, competence: str, filename: str) -> Path:
        entry = self.get(competence)
        if not entry: raise KeyError(competence)
        if not re.fullmatch(r"Estabelecimentos\d+\.zip", filename, re.IGNORECASE):
            raise ValueError("Arquivo de Estabelecimentos inválido.")
        folder = Path(entry["path"]).resolve()
        path = folder / filename
        if path.is_symlink() or path.resolve().parent != folder or not path.is_file():
            raise ValueError("Arquivo local não encontrado.")
        return path

    def reference_file_path(self, name: str) -> Path:
        if name not in {"Cnaes.zip", "Municipios.zip", "Motivos.zip", "Paises.zip", "MunicipiosUF.csv", "CNAE_Subclasses_2_3_Estrutura_Detalhada.xlsx"}:
            raise ValueError("Tabela auxiliar desconhecida.")
        root = (self.data_dir / "referencias").resolve()
        try:
            meta = json.loads((root / "atual.json").read_text(encoding="utf-8")).get("references", {}).get(name, {})
        except (OSError, ValueError):
            meta = {}
        path = Path(meta["path"]) if meta.get("path") else None
        if not path or path.is_symlink() or not path.is_file() or path.name != name or root not in path.resolve().parents:
            raise ValueError("Tabela auxiliar local não encontrada.")
        return path

    def remove_reference(self, name: str) -> dict:
        names = {"Cnaes.zip", "Municipios.zip", "Motivos.zip", "Paises.zip", "MunicipiosUF.csv", "CNAE_Subclasses_2_3_Estrutura_Detalhada.xlsx"}
        if name not in names: raise ValueError("Tabela auxiliar desconhecida.")
        root = (self.data_dir / "referencias").resolve()
        candidates = list((root / "entrada").glob(f"*/{name}")) + list((root / "versoes").glob(f"*/{name}"))
        removed = 0
        for path in candidates:
            if path.is_file() and not path.is_symlink() and root in path.resolve().parents:
                send2trash(str(path)); removed += 1
        current_path = root / "atual.json"
        try:
            current = json.loads(current_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {"references": {}}
        current.setdefault("references", {}).pop(name, None)
        temporary = current_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(current_path)
        return {"ok": True, "message": f"{name}: {removed} cópia(s) enviadas à Lixeira.", "removed": removed}

    def clear_geocoding_cache(self) -> dict:
        cache = (Path(os.getenv("GEOCNPJ_GEO_RUNTIME_DIR", str(self.data_dir / "geo_runtime"))) / "cache").resolve()
        if not cache.is_dir() or cache.is_symlink():
            return {"ok": True, "message": "O cache de geocodificação já está vazio.", "removed": 0}
        removed = 0
        for path in cache.iterdir():
            if path.is_symlink(): continue
            send2trash(str(path)); removed += 1
        return {"ok": True, "message": f"Cache de geocodificação enviado à Lixeira ({removed} item(ns)).", "removed": removed}

    def import_folder(self, competence: str, folder: str) -> dict:
        path = Path(folder).expanduser().resolve()
        if not path.exists() or not path.is_dir(): raise ValueError("A pasta informada não existe ou não é um diretório.")
        return self.register(competence, path, "pasta_existente", False)

    def destination(self, competence: str, root: str | None = None) -> Path:
        if root and root.strip():
            base = Path(root.strip()).expanduser().resolve()
            base.mkdir(parents=True, exist_ok=True)
            folder = base / competence
        else:
            folder = self.data_dir / "competencias" / competence
        current = self.get(competence)
        if folder.exists() and any(folder.iterdir()) and not current:
            raise ValueError("A pasta de destino já contém arquivos. Use 'Usar arquivos existentes' para validá-la sem risco.")
        self.register(competence, folder, "download", True)
        return folder

    def remove(self, competence: str, delete_files: bool) -> dict:
        data = self._load(); entry = data.get("locations", {}).get(competence)
        if not entry: raise KeyError(competence)
        folder = Path(entry["path"]).resolve()
        deleted = False
        if delete_files:
            if not entry.get("managed"):
                raise ValueError("Pastas externas vinculadas não podem ser apagadas pelo GeoCNPJ. Remova apenas o vínculo.")
            if not folder.exists():
                deleted = True
            else:
                if folder.name != competence or folder == self.data_dir or folder.parent == folder:
                    raise ValueError("Destino de exclusão recusado por segurança.")
                send2trash(str(folder)); deleted = True
        data["locations"].pop(competence, None); self._save(data)
        return {"ok": True, "competence": competence, "files_sent_to_trash": deleted,
                "message": "Arquivos enviados à Lixeira." if deleted else "Vínculo removido; arquivos externos preservados."}

    def disk_usage(self, path: str | None = None) -> dict:
        target = Path(path).expanduser().resolve() if path else self.data_dir
        existing = target
        while not existing.exists() and existing != existing.parent: existing = existing.parent
        usage = shutil.disk_usage(existing)
        return {"path": str(target), "total": usage.total, "used": usage.used, "free": usage.free}

    @staticmethod
    def _folder_size(folder: Path) -> tuple[int, int]:
        """Return physical bytes and file count without following directory symlinks."""
        if not folder.exists() or not folder.is_dir():
            return 0, 0
        size = count = 0
        try:
            candidates = folder.rglob("*")
            for path in candidates:
                try:
                    if path.is_file() and not path.is_symlink():
                        size += path.stat().st_size
                        count += 1
                except OSError:
                    continue
        except OSError:
            pass
        return size, count

    def storage_overview(self, processes: list[dict], geocodings: list[dict], projects: list[dict],
                         validated: set[str] | None = None) -> dict:
        """Build a deduplicated view of physical artifacts and project references."""
        competences = self.inventory(validated)
        references = self.references_inventory()
        artifacts: dict[str, dict] = {}

        def add_artifact(key: str, kind: str, label: str, path: Path, managed: bool = True, **metadata):
            resolved = path.expanduser().resolve()
            size, file_count = self._folder_size(resolved)
            item = {"key": key, "kind": kind, "label": label, "path": str(resolved), "managed": managed,
                    "exists": resolved.exists(), "size": size, "file_count": file_count, **metadata}
            artifacts[key] = item
            return item

        competence_rows = []
        for entry in competences:
            item = add_artifact(f"competence:{entry['competence']}", "competence", entry["competence"],
                                Path(entry["path"]), bool(entry.get("managed")), competence=entry["competence"],
                                validated=entry.get("validated", False), origin=entry.get("origin"))
            competence_rows.append(item)

        process_rows = []
        for process in processes:
            job_id = process.get("job_id")
            if not job_id:
                continue
            item = add_artifact(f"process:{job_id}", "process", process.get("municipality_name") or job_id,
                                self.data_dir / "processamentos" / job_id, job_id=job_id,
                                status=process.get("status"), competence=process.get("competence"), uf=process.get("uf"),
                                municipality_name=process.get("municipality_name"), rows=process.get("rows_found", 0))
            process_rows.append(item)

        geocoding_rows = []
        for geocoding in geocodings:
            job_id = geocoding.get("job_id")
            if not job_id:
                continue
            item = add_artifact(f"geocoding:{job_id}", "geocoding", geocoding.get("municipality_name") or job_id,
                                self.data_dir / "geocodificacoes" / job_id, job_id=job_id,
                                process_job_id=geocoding.get("process_job_id"), status=geocoding.get("status"),
                                competence=geocoding.get("competence"), municipality_name=geocoding.get("municipality_name"))
            geocoding_rows.append(item)

        project_keys: dict[str, list[str]] = {}
        reference_count: dict[str, int] = {}
        for project in projects:
            keys = []
            competence_key = f"competence:{project.get('competence')}"
            process_key = f"process:{project.get('process_job_id')}"
            geocoding_key = f"geocoding:{project.get('geocoding_job_id')}"
            for key in (competence_key, process_key, geocoding_key):
                if key in artifacts and key not in keys:
                    keys.append(key)
                    reference_count[key] = reference_count.get(key, 0) + 1
            project_keys[project["project_id"]] = keys

        for item in artifacts.values():
            item["project_count"] = reference_count.get(item["key"], 0)
            item["shared"] = item["project_count"] > 1

        project_rows = []
        for project in projects:
            linked = [artifacts[key] for key in project_keys.get(project["project_id"], [])]
            logical = sum(item["size"] for item in linked)
            shared = sum(item["size"] for item in linked if item["shared"])
            project_rows.append({"project_id": project["project_id"], "name": project.get("name"),
                                 "logical_size": logical, "shared_size": shared,
                                 "exclusive_size": logical - shared, "artifact_count": len(linked)})

        managed = [item for item in artifacts.values() if item["managed"]]
        external = [item for item in artifacts.values() if not item["managed"]]
        disk = self.disk_usage()
        return {
            "summary": {"physical_size": sum(item["size"] for item in managed) + references["stored_size"],
                        "external_size": sum(item["size"] for item in external),
                        "shared_size": sum(item["size"] for item in artifacts.values() if item["shared"]),
                        "unlinked_size": sum(item["size"] for item in managed if not item["project_count"]),
                        "reference_size": references["stored_size"],
                        "free": disk["free"], "disk_total": disk["total"], "data_path": str(self.data_dir)},
            "references": references,
            "competences": sorted(competence_rows, key=lambda row: row["label"], reverse=True),
            "processes": sorted(process_rows, key=lambda row: (row.get("competence") or "", row["job_id"]), reverse=True),
            "geocodings": sorted(geocoding_rows, key=lambda row: (row.get("competence") or "", row["job_id"]), reverse=True),
            "projects": project_rows,
        }
