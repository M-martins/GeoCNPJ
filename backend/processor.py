from __future__ import annotations

import json
import csv
import re
import threading
import time
import uuid
import zipfile
from functools import lru_cache
from itertools import islice
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd

from .catalog import ESTABLISHMENT_RE, ReceitaCatalog, MUNICIPALITY_UF_NAME, CNAE_HIERARCHY_NAME
from .cnae_hierarchy import load_cnae_hierarchy
from .storage import StorageLibrary


ESTABLISHMENT_COLUMNS = [
    "cnpj_basico", "cnpj_ordem", "cnpj_dv", "identificador_matriz_filial",
    "nome_fantasia", "situacao_cadastral", "data_situacao_cadastral",
    "motivo_situacao_cadastral", "nome_cidade_exterior", "pais",
    "data_inicio_atividade", "cnae_fiscal_principal", "cnae_fiscal_secundaria",
    "tipo_logradouro", "logradouro", "numero", "complemento", "bairro", "cep",
    "uf", "municipio_codigo_receita", "ddd_1", "telefone_1", "ddd_2",
    "telefone_2", "ddd_fax", "fax", "correio_eletronico",
    "situacao_especial", "data_situacao_especial",
]
SITUATIONS = {"01": "NULA", "02": "ATIVA", "03": "SUSPENSA", "04": "INAPTA", "08": "BAIXADA"}
EXPECTED_REFERENCES = ["Cnaes.zip", "Municipios.zip", "Motivos.zip", "Paises.zip", MUNICIPALITY_UF_NAME]


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def clean_alphanumeric(value) -> str:
    """Preserva letras do CNPJ alfanumérico e remove apenas formatação."""
    if value is None or pd.isna(value):
        return ""
    text = re.sub(r"\.0$", "", str(value).strip().replace('"', ""))
    return re.sub(r"[^0-9A-Z]", "", text.upper())


def clean_digits(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"\D", "", re.sub(r"\.0$", "", str(value).strip()))


def build_cnpj(frame: pd.DataFrame) -> pd.Series:
    base = frame["cnpj_basico"].map(clean_alphanumeric).str.zfill(8)
    order = frame["cnpj_ordem"].map(clean_alphanumeric).str.zfill(4)
    check = frame["cnpj_dv"].map(clean_alphanumeric).str.zfill(2)
    return base + order + check


class ReferenceLibrary:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "referencias"

    def current(self) -> dict:
        path = self.root / "atual.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("references", {})
        except (OSError, json.JSONDecodeError):
            return {}

    def path(self, name: str) -> Path:
        item = self.current().get(name)
        if not item or not Path(item.get("path", "")).exists():
            raise FileNotFoundError(f"Referência central ausente: {name}")
        return Path(item["path"])

    def read(self, name: str, columns: list[str], references: dict | None = None) -> pd.DataFrame:
        if references is None:
            path = self.path(name)
        else:
            item = references.get(name, {})
            path = Path(item.get("path", ""))
            if not path.exists(): raise FileNotFoundError(f"Versão registrada da referência não encontrada: {name}")
        with zipfile.ZipFile(path) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if not members:
                raise ValueError(f"Referência vazia: {name}")
            with archive.open(members[0]) as source:
                return pd.read_csv(source, sep=";", header=None, names=columns, dtype=str,
                                   encoding="latin1", quotechar='"', on_bad_lines="skip")

    @staticmethod
    @lru_cache(maxsize=4)
    def _municipality_index(path: str, modified_ns: int, size: int) -> tuple[tuple[str, str, str], ...]:
        with zipfile.ZipFile(path) as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
            if not members:
                raise ValueError("Referência de municípios vazia.")
            with archive.open(members[0]) as source:
                frame = pd.read_csv(source, sep=";", header=None, names=["code", "name"],
                                    dtype=str, encoding="latin1", quotechar='"', on_bad_lines="skip")
        frame["code"] = frame["code"].map(clean_digits).str.zfill(4)
        frame["name"] = frame["name"].fillna("").str.strip()
        return tuple((row.code, row.name, unicodedata.normalize("NFKD", row.name).encode("ascii", "ignore").decode().upper())
                     for row in frame.itertuples(index=False))

    @staticmethod
    @lru_cache(maxsize=4)
    def _municipality_uf_index(path: str, modified_ns: int, size: int) -> dict[str, str]:
        mapping = {}
        with Path(path).open(encoding="latin1", newline="") as source:
            rows = csv.reader(source, delimiter=";")
            header = next(rows, [])
            if len(header) != 5 or header[-1].strip().upper() != "UF":
                raise ValueError("Complemento municipal da Receita com formato inesperado.")
            for row in rows:
                if len(row) == 5 and row[0].strip().isdigit():
                    mapping[row[0].strip().zfill(4)] = row[4].strip().upper()
        # Município criado após a publicação da lista complementar de 2023.
        mapping["1182"] = "MT"
        return mapping

    def _municipality_ufs(self) -> dict[str, str]:
        path = self.path(MUNICIPALITY_UF_NAME)
        stat = path.stat()
        return self._municipality_uf_index(str(path), stat.st_mtime_ns, stat.st_size)

    def municipalities(self, query: str = "", uf: str = "") -> list[dict]:
        path = self.path("Municipios.zip")
        stat = path.stat()
        index = self._municipality_index(str(path), stat.st_mtime_ns, stat.st_size)
        ufs = self._municipality_ufs()
        uf = uf.strip().upper()
        normalized = unicodedata.normalize("NFKD", query.strip()).encode("ascii", "ignore").decode().upper()
        matches = (row for row in index if (not uf or ufs.get(row[0]) == uf)
                   and (not normalized or normalized in row[2] or normalized in row[0]))
        return [{"code": code, "name": name, "uf": ufs.get(code)} for code, name, _ in islice(matches, 100)]

    def maps(self, references: dict | None = None) -> dict:
        cnae = self.read("Cnaes.zip", ["code", "description"], references)
        reasons = self.read("Motivos.zip", ["code", "description"], references)
        countries = self.read("Paises.zip", ["code", "description"], references)
        hierarchy_meta = (references or self.current()).get(CNAE_HIERARCHY_NAME, {})
        hierarchy_path = Path(hierarchy_meta["path"]) if hierarchy_meta.get("path") else None
        if hierarchy_path and not hierarchy_path.is_file():
            hierarchy_path = None
        return {
            "cnae": {clean_digits(r.code).zfill(7): str(r.description or "").strip() for r in cnae.itertuples()},
            "cnae_hierarchy": load_cnae_hierarchy(hierarchy_path) if hierarchy_path else {},
            "reasons": {clean_digits(r.code).zfill(2): str(r.description or "").strip() for r in reasons.itertuples()},
            "countries": {clean_digits(r.code).zfill(3): str(r.description or "").strip() for r in countries.itertuples()},
        }


class MunicipalProcessor:
    def __init__(self, data_dir: Path, catalog: ReceitaCatalog, library: StorageLibrary, store=None):
        self.data_dir = data_dir
        self.catalog = catalog
        self.library = library
        self.store = store
        self.competences_dir = data_dir / "competencias"
        self.jobs_dir = data_dir / "processamentos"
        self.manifests_dir = data_dir / "controle" / "competencias"
        self.validation_dir = data_dir / "controle" / "validacoes"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.manifests_dir.mkdir(parents=True, exist_ok=True)
        self.validation_dir.mkdir(parents=True, exist_ok=True)
        self.references = ReferenceLibrary(data_dir)
        self._cancel: dict[str, threading.Event] = {}

    def _validation_path(self, validation_id): return self.validation_dir / f"{validation_id}.json"

    def _save_validation(self, state):
        path = self._validation_path(state["validation_id"]); temp = path.with_suffix(".json.tmp")
        state["updated_at"] = now_iso()
        if self.store: self.store.put_operation("validation", state["validation_id"], state, path)
        for attempt in range(6):
            try: temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"); temp.replace(path); return
            except PermissionError:
                if attempt == 5: raise
                time.sleep(.03 * (attempt + 1))

    def get_validation(self, validation_id):
        if self.store:
            stored = self.store.get_operation("validation", validation_id)
            if stored is not None: return stored
        path = self._validation_path(validation_id)
        if not path.exists(): raise KeyError(validation_id)
        for attempt in range(6):
            try: return json.loads(path.read_text(encoding="utf-8"))
            except (PermissionError, json.JSONDecodeError):
                if attempt == 5: raise
                time.sleep(.03 * (attempt + 1))

    def start_validation(self, competence):
        validation_id = uuid.uuid4().hex[:10]
        state = {"validation_id": validation_id, "competence": competence, "status": "queued", "percent": 0,
                 "current_file": None, "files_completed": 0, "total_files": 0, "message": "Validação na fila.", "created_at": now_iso()}
        self._save_validation(state)
        threading.Thread(target=self._run_validation, args=(validation_id,), daemon=True).start()
        return state

    def _run_validation(self, validation_id):
        state = self.get_validation(validation_id); state["status"] = "running"; self._save_validation(state)
        def progress(current_file, completed, total, message):
            state.update(current_file=current_file, files_completed=completed, total_files=total, message=message,
                         percent=round(completed * 100 / total, 2) if total else 0)
            self._save_validation(state)
        try:
            manifest = self.validate_competence(state["competence"], progress)
            state.update(status="completed", percent=100, current_file=None, files_completed=len(manifest["files"]),
                         total_files=len(manifest["files"]), message=f"Dados do mês validados com {len(manifest['files'])} arquivo(s).")
        except Exception as exc:
            state.update(status="error", message=str(exc))
        self._save_validation(state)

    def _manifest_path(self, competence: str) -> Path:
        return self.manifests_dir / f"{competence}.json"

    def _load_manifest(self, competence: str) -> dict | None:
        path = self._manifest_path(competence)
        try: return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return None

    def _official_establishments(self, competence: str) -> list[dict]:
        return [item for item in self.catalog.files(competence) if item["kind"] == "establishment"]

    def _local_signature(self, folder: Path, names: list[str]) -> list[dict]:
        signature = []
        for name in names:
            path = folder / name
            if path.exists():
                stat = path.stat()
                signature.append({"name": name, "size": stat.st_size, "modified_ns": stat.st_mtime_ns})
        return signature

    def readiness(self) -> dict:
        references = self.references.current()
        competences = []
        self.library.ensure_legacy()
        for item in self.library.inventory():
            folder = Path(item["path"])
            competence = item["competence"]
            manifest = self._load_manifest(competence)
            expected = manifest.get("files", []) if manifest else []
            names = [expected_item["name"] for expected_item in expected]
            signature_matches = bool(manifest and manifest.get("local_signature") == self._local_signature(folder, names))
            validated = bool(manifest and manifest.get("status") == "validated" and signature_matches)
            local_names = sorted(p.name for p in folder.glob("*.zip") if ESTABLISHMENT_RE.fullmatch(p.name))
            competences.append({"competence": competence, "validated": validated, "path": str(folder),
                                "expected": len(names) if names else None, "present": len(local_names),
                                "missing": [name for name in names if not (folder / name).exists()] if names else [],
                                "needs_validation": not validated})
        missing_refs = [name for name in EXPECTED_REFERENCES if name not in references or not Path(references[name].get("path", "")).exists()]
        return {"competences": competences, "references_complete": not missing_refs, "missing_references": missing_refs,
                "ready_competences": [c["competence"] for c in competences if c["validated"]]}

    def validate_competence(self, competence: str, progress=None) -> dict:
        folder = self.library.path(competence)
        if folder is None: raise ValueError("O mês dos dados ainda não está registrado no Acervo.")
        if not folder.exists(): raise ValueError("Os dados deste mês ainda não possuem uma pasta local.")
        official = self._official_establishments(competence)
        if not official: raise ValueError("O catálogo oficial não publicou arquivos de estabelecimentos para este mês.")
        official_names = [item["name"] for item in official]
        local_names = sorted(p.name for p in folder.glob("*.zip") if ESTABLISHMENT_RE.fullmatch(p.name))
        missing = [name for name in official_names if name not in local_names]
        extra = [name for name in local_names if name not in official_names]
        wrong_size = []
        if missing: raise ValueError("Arquivos oficiais ausentes: " + ", ".join(missing))
        for item in official:
            path = folder / item["name"]
            if item.get("size") and path.stat().st_size != item["size"]:
                wrong_size.append(item["name"])
        if wrong_size: raise ValueError("Arquivos com tamanho diferente do catálogo: " + ", ".join(wrong_size))
        total = len(official)
        for index, item in enumerate(official, 1):
            if progress: progress(item["name"], index - 1, total, f"Validando integridade de {item['name']}...")
            with zipfile.ZipFile(folder / item["name"]) as archive:
                bad = archive.testzip()
                if bad: raise ValueError(f"ZIP corrompido em {item['name']}: {bad}")
            if progress: progress(item["name"], index, total, f"{item['name']} validado ({index}/{total}).")
        refs = self.references.current()
        missing_refs = [name for name in EXPECTED_REFERENCES if name not in refs or not Path(refs[name].get("path", "")).exists()]
        if missing_refs: raise ValueError("Referências centrais ausentes: " + ", ".join(missing_refs))
        manifest = {"competence": competence, "status": "validated", "validated_at": now_iso(),
                    "source": "Receita Federal / SERPRO", "files": official, "extra_files": extra,
                    "local_signature": self._local_signature(folder, official_names),
                    "references": {name: refs[name] for name in EXPECTED_REFERENCES + [CNAE_HIERARCHY_NAME]
                                   if name in refs and Path(refs[name].get("path", "")).is_file()}}
        path = self._manifest_path(competence); temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"); temporary.replace(path)
        return manifest

    def _status_path(self, job_id):
        return self.jobs_dir / job_id / "status.json"

    def _save(self, job):
        job["updated_at"] = now_iso(); path = self._status_path(job["job_id"]); path.parent.mkdir(parents=True, exist_ok=True)
        if self.store: self.store.put_operation("process", job["job_id"], job, path)
        temporary = path.with_suffix(".json.tmp")
        for attempt in range(5):
            try:
                temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 4: raise
                time.sleep(.03 * (attempt + 1))

    def get(self, job_id):
        if self.store:
            stored = self.store.get_operation("process", job_id)
            if stored is not None: return stored
        path = self._status_path(job_id)
        if not path.exists(): raise KeyError(job_id)
        for attempt in range(8):
            try: return json.loads(path.read_text(encoding="utf-8"))
            except (PermissionError, json.JSONDecodeError):
                if attempt == 7: raise
                time.sleep(.02 * (attempt + 1))

    def list(self):
        if self.store: return self.store.list_operations("process")
        jobs = []
        for path in self.jobs_dir.glob("*/status.json"):
            try: jobs.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError): pass
        return sorted(jobs, key=lambda j: j.get("created_at", ""), reverse=True)

    def create(self, competence: str, uf: str, municipality_code: str, municipality_name: str,
               active_only: bool = True, output_format: str = "csv", accept_incomplete: bool = False):
        ready = self.readiness()
        if not ready["references_complete"]:
            raise ValueError("Referências centrais ausentes: " + ", ".join(ready["missing_references"]))
        uf = uf.strip().upper(); municipality_code = clean_digits(municipality_code).zfill(4)
        if not re.fullmatch(r"[A-Z]{2}", uf): raise ValueError("UF inválida.")
        if output_format not in {"csv", "parquet"}: raise ValueError("Formato de saída inválido.")
        source_dir = self.library.path(competence)
        if source_dir is None: raise ValueError("Nenhum arquivo deste mês foi encontrado no computador.")
        official = self._official_establishments(competence)
        if not official: raise ValueError("O catálogo da Receita não encontrou partes deste mês.")
        available = [item for item in official if (source_dir / item["name"]).is_file()]
        if not available: raise ValueError("Baixe pelo menos uma parte de Estabelecimentos antes de processar.")
        for item in available:
            path = source_dir / item["name"]
            if item.get("size") and path.stat().st_size != item["size"]:
                raise ValueError(f"O download de {item['name']} está incompleto. Baixe esta parte novamente.")
            if not zipfile.is_zipfile(path):
                raise ValueError(f"O arquivo {item['name']} não é um ZIP válido. Baixe esta parte novamente.")
        missing = [item["name"] for item in official if item not in available]
        is_partial = bool(missing)
        if is_partial and not accept_incomplete:
            raise ValueError("Confirme que deseja processar apenas as partes baixadas, com cobertura incompleta.")
        if not is_partial and competence not in ready["ready_competences"]:
            raise ValueError("Os arquivos completos ainda estão sendo conferidos. Aguarde a conclusão da conferência.")
        manifest = self._load_manifest(competence) if not is_partial else None
        current_references = self.references.current()
        references = dict(manifest["references"]) if manifest else {
            name: current_references[name] for name in EXPECTED_REFERENCES + [CNAE_HIERARCHY_NAME]
            if name in current_references and Path(current_references[name].get("path", "")).is_file()}
        # A planilha opcional pode ser baixada depois da conferência do mês.
        hierarchy = current_references.get(CNAE_HIERARCHY_NAME, {})
        if hierarchy.get("path") and Path(hierarchy["path"]).is_file():
            references[CNAE_HIERARCHY_NAME] = hierarchy
        source_files = [item["name"] for item in available]
        job_id = uuid.uuid4().hex[:10]
        job = {"job_id": job_id, "status": "queued", "competence": competence, "uf": uf,
               "municipality_code": municipality_code, "municipality_name": municipality_name.strip().upper(),
               "active_only": active_only, "output_format": output_format, "created_at": now_iso(),
               "current_file": None, "files_completed": 0, "total_files": len(source_files), "source_files": source_files,
               "official_file_count": len(official), "missing_source_files": missing,
               "is_partial": is_partial, "incomplete_acknowledged_at": now_iso() if is_partial else None,
               "references": references,
               "source_signatures": self._local_signature(source_dir, source_files),
               "rows_read": 0, "rows_found": 0,
               "percent": 0, "logs": [f"{now_iso()} - Processamento municipal criado."]}
        if is_partial:
            self._log(job, f"Cobertura parcial aceita pelo usuário: {len(source_files)} de {len(official)} partes oficiais. Resultados podem omitir estabelecimentos.")
        self._save(job); event = threading.Event(); self._cancel[job_id] = event
        threading.Thread(target=self._run, args=(job_id, event), daemon=True).start()
        return job

    def cancel(self, job_id):
        job = self.get(job_id); self._cancel.setdefault(job_id, threading.Event()).set()
        if job["status"] in {"queued", "running"}: job["status"] = "cancelling"; self._log(job, "Cancelamento solicitado."); self._save(job)
        elif job["status"] in {"interrupted", "error"}: job["status"] = "cancelled"; self._log(job, "Execução encerrada; arquivos parciais foram preservados."); self._save(job)
        return job

    def resume(self, job_id):
        job = self.get(job_id)
        if job.get("status") not in {"interrupted", "error", "cancelled"}:
            raise ValueError("Este processamento não pode ser retomado.")
        partials = self._status_path(job_id).parent / "partials"
        completed = int(job.get("files_completed") or 0)
        rows_found = 0
        for index in range(completed):
            partial = partials / f"partial_{index:02d}.csv"
            if partial.exists():
                try:
                    rows_found += sum(len(chunk) for chunk in pd.read_csv(partial, sep=";", dtype=str,
                                                                             encoding="utf-8-sig", chunksize=50_000))
                except Exception: pass
        job.update(status="queued", current_file=None, rows_found=rows_found, rows_read=0)
        self._log(job, "Processamento retomado a partir dos arquivos parciais válidos."); self._save(job)
        event = threading.Event(); self._cancel[job_id] = event
        threading.Thread(target=self._run, args=(job_id, event), daemon=True).start()
        return job

    def _log(self, job, message):
        job.setdefault("logs", []).append(f"{now_iso()} - {message}"); job["logs"] = job["logs"][-100:]

    def _run(self, job_id, cancel):
        run_started = time.perf_counter()
        job = self.get(job_id); job_dir = self._status_path(job_id).parent; partials = job_dir / "partials"; partials.mkdir(exist_ok=True)
        job["status"] = "running"; job["started_at"] = now_iso(); self._save(job)
        try:
            maps = self.references.maps(job.get("references") or self._load_manifest(job["competence"])["references"])
            source_dir = self.library.path(job["competence"])
            if source_dir is None: raise ValueError("A pasta registrada para este mês não foi encontrada.")
            source_files = job["source_files"]
            for index, name in enumerate(source_files):
                partial = partials / f"partial_{index:02d}.csv"
                if index < int(job.get("files_completed") or 0) and partial.exists():
                    continue
                if partial.exists(): partial.unlink()
                if cancel.is_set(): raise InterruptedError
                job["current_file"] = name; self._save(job)
                self._process_zip(source_dir / name, partial, job, maps, cancel, index)
                job["files_completed"] = index + 1; job["percent"] = round((index + 1) * 100 / len(source_files), 2); self._log(job, f"{name} concluído."); self._save(job)
            final = self._finish(job_dir, job)
            job["status"] = "completed"; job["current_file"] = None; job["output_file"] = final.name
            job["download_url"] = f"/api/processes/{job_id}/download"; self._log(job, f"Base municipal gerada: {final.name}.")
        except InterruptedError:
            job["status"] = "cancelled"; self._log(job, "Processamento cancelado.")
        except Exception as exc:
            job["status"] = "error"; self._log(job, f"Falha: {exc}")
        finally:
            job["processing_seconds"] = round(float(job.get("processing_seconds") or 0) + time.perf_counter() - run_started, 2)
            job["finished_at"] = now_iso()
            self._save(job); self._cancel.pop(job_id, None)

    def _process_zip(self, path, partial, job, maps, cancel, file_index):
        expected_signature = next((item for item in job.get("source_signatures", []) if item["name"] == path.name), None)
        if expected_signature:
            stat = path.stat()
            if stat.st_size != expected_signature["size"] or stat.st_mtime_ns != expected_signature["modified_ns"]:
                raise ValueError(f"O arquivo {path.name} mudou após a seleção. Inicie uma nova preparação.")
        wrote_header = False
        last_progress_save = 0.0
        with zipfile.ZipFile(path) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if not members: raise ValueError(f"ZIP vazio: {path.name}")
            with archive.open(members[0]) as source:
                reader = pd.read_csv(source, sep=";", header=None, names=ESTABLISHMENT_COLUMNS, dtype=str,
                                     encoding="latin1", chunksize=100_000, low_memory=False, quotechar='"')
                for chunk_number, chunk in enumerate(reader, 1):
                    if cancel.is_set(): raise InterruptedError
                    job["rows_read"] += len(chunk)
                    # A base oficial usa UF, codigo municipal da Receita e situacao em campos de largura fixa.
                    # Comparações diretas evitam normalizar milhões de linhas em Python.
                    mask = chunk["uf"].eq(job["uf"])
                    mask &= chunk["municipio_codigo_receita"].eq(job["municipality_code"])
                    if job["active_only"]: mask &= chunk["situacao_cadastral"].eq("02")
                    selected = chunk[mask].copy()
                    if not selected.empty:
                        selected = enrich(selected, job["municipality_name"], maps)
                        selected.to_csv(partial, sep=";", index=False, encoding="utf-8-sig", mode="a", header=not wrote_header)
                        wrote_header = True; job["rows_found"] += len(selected)
                    job["percent"] = round(min((file_index + min(chunk_number / (chunk_number + 5), .95)) * 100 / job["total_files"], 99), 2)
                    if chunk_number == 1 or chunk_number % 10 == 0: self._log(job, f"{path.name}: {job['rows_read']:,} linhas lidas, {job['rows_found']:,} encontradas.")
                    now = time.monotonic()
                    if chunk_number == 1 or now - last_progress_save >= 2:
                        self._save(job)
                        last_progress_save = now

    def _finish(self, job_dir, job):
        partials = sorted((job_dir / "partials").glob("*.csv"))
        if not partials:
            if job.get("is_partial"):
                raise ValueError("Nenhum registro apareceu nas partes escolhidas. Isso não prova que o município não tem estabelecimentos; baixe outras partes do mês.")
            raise ValueError("Nenhum estabelecimento foi encontrado para os filtros escolhidos.")
        import pyarrow as pa
        import pyarrow.parquet as pq

        base = f"cnpj_{job['competence']}_{job['uf'].lower()}_{job['municipality_code']}_{job['job_id']}"
        output = job_dir / (base + (".csv" if job["output_format"] == "csv" else ".parquet"))
        temporary = output.with_name(output.name + ".tmp")
        row_count = 0
        writer = None
        columns = None
        try:
            for path in partials:
                for frame in pd.read_csv(path, sep=";", dtype=str, encoding="utf-8-sig", chunksize=50_000):
                    if columns is None:
                        columns = list(frame.columns)
                    elif list(frame.columns) != columns:
                        raise ValueError(f"As colunas de {path.name} diferem das outras partes; reinicie a preparacao.")
                    frame["cobertura_parcial"] = bool(job.get("is_partial"))
                    frame["partes_usadas"] = len(job["source_files"])
                    frame["partes_oficiais"] = job.get("official_file_count", len(job["source_files"]))
                    if job["output_format"] == "csv":
                        frame.to_csv(temporary, sep=";", index=False, mode="w" if row_count == 0 else "a",
                                     header=row_count == 0, encoding="utf-8-sig" if row_count == 0 else "utf-8")
                    else:
                        table = pa.Table.from_pandas(frame, preserve_index=False)
                        if writer is None:
                            writer = pq.ParquetWriter(temporary, table.schema)
                        writer.write_table(table)
                    row_count += len(frame)
            if writer is not None:
                writer.close()
                writer = None
            temporary.replace(output)
        except Exception:
            if writer is not None:
                writer.close()
            temporary.unlink(missing_ok=True)
            raise
        summary = pd.DataFrame([{"competencia": job["competence"], "uf": job["uf"], "municipio": job["municipality_name"],
                                 "linhas_lidas": job["rows_read"], "linhas_resultado": row_count, "somente_ativas": job["active_only"],
                                 "cobertura_parcial": job.get("is_partial", False), "partes_usadas": len(job["source_files"]),
                                 "partes_oficiais": job.get("official_file_count", len(job["source_files"])),
                                 "partes_ausentes": ", ".join(job.get("missing_source_files", [])),
                                 "aceite_cobertura_incompleta_em": job.get("incomplete_acknowledged_at") or ""}])
        summary.to_csv(job_dir / "resumo_processamento.csv", sep=";", index=False, encoding="utf-8-sig")
        return output

    def output_path(self, job_id):
        job = self.get(job_id)
        if job.get("status") != "completed": raise ValueError("O processamento ainda não foi concluído.")
        path = self._status_path(job_id).parent / job["output_file"]
        if not path.exists(): raise FileNotFoundError(path)
        return path


def enrich(frame: pd.DataFrame, municipality_name: str, maps: dict) -> pd.DataFrame:
    frame = frame.copy(); frame["cnpj_completo"] = build_cnpj(frame)
    for component, width in (("cnpj_basico", 8), ("cnpj_ordem", 4), ("cnpj_dv", 2)):
        frame[component] = frame[component].map(clean_alphanumeric).str.zfill(width)
    frame["cep"] = frame["cep"].map(clean_digits).str.zfill(8)
    frame["situacao_cadastral"] = frame["situacao_cadastral"].map(clean_digits).str.zfill(2)
    frame["situacao_cadastral_desc"] = frame["situacao_cadastral"].map(SITUATIONS).fillna("")
    frame["motivo_situacao_cadastral"] = frame["motivo_situacao_cadastral"].map(clean_digits).str.zfill(2)
    frame["motivo_situacao_cadastral_desc"] = frame["motivo_situacao_cadastral"].map(maps["reasons"]).fillna("")
    frame["pais"] = frame["pais"].map(clean_digits).str.zfill(3); frame["pais_desc"] = frame["pais"].map(maps["countries"]).fillna("")
    frame["cnae_fiscal_principal"] = frame["cnae_fiscal_principal"].map(clean_digits).str.zfill(7)
    frame["cnae_principal_desc"] = frame["cnae_fiscal_principal"].map(maps["cnae"]).fillna("")
    hierarchy = maps.get("cnae_hierarchy", {})
    for column in ("cnae_secao_codigo", "cnae_secao_descricao", "cnae_divisao_codigo", "cnae_divisao_descricao",
                   "cnae_grupo_codigo", "cnae_grupo_descricao"):
        frame[column] = frame["cnae_fiscal_principal"].map(lambda code: hierarchy.get(code, {}).get(column, ""))
    frame["municipio_nome"] = municipality_name
    frame["endereco_completo"] = (frame["tipo_logradouro"].fillna("").str.strip()+" "+frame["logradouro"].fillna("").str.strip()+", "+
        frame["numero"].fillna("").str.strip()+", "+frame["bairro"].fillna("").str.strip()+", "+municipality_name+" - "+
        frame["uf"].fillna("").str.strip()+", "+frame["cep"]).str.replace(r"\s+", " ", regex=True).str.strip(" ,")
    first = ["cnpj_completo", "nome_fantasia", "situacao_cadastral", "situacao_cadastral_desc", "cnae_fiscal_principal",
             "cnae_principal_desc", "cnae_secao_codigo", "cnae_secao_descricao", "cnae_divisao_codigo",
             "cnae_divisao_descricao", "cnae_grupo_codigo", "cnae_grupo_descricao", "endereco_completo", "uf",
             "municipio_codigo_receita", "municipio_nome"]
    return frame[first + [c for c in frame.columns if c not in first]]
