from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path

import requests

from .processor import MunicipalProcessor, now_iso
from .geojson_stream import stream_geojson


QUALITY_LABELS = {"high": "Alta confiança", "alert": "Aceito com alerta", "review": "Precisa de revisão", "unknown": "Não classificada"}


def classify_quality(properties: dict) -> str:
    decision = str(properties.get("decisao_geocode", "")).lower()
    if decision == "aceito_automaticamente": return "high"
    if decision == "aceito_com_alerta": return "alert"
    if decision.startswith("revisar") or str(properties.get("necessita_revisao", "")).lower() in {"true", "1", "sim"}: return "review"
    return "unknown"


def prepare_map_geojson(source: Path, destination: Path) -> dict:
    counts = {key: 0 for key in QUALITY_LABELS}
    keep = ["cnpj_completo", "nome_fantasia", "endereco_completo", "logradouro", "numero", "bairro", "score_geocode", "decisao_geocode",
            "necessita_revisao", "precisao", "desvio_metros", "qtd_candidatos", "geocode_status"]
    metadata = {}
    mapped = 0
    features_file = destination.with_name(destination.name + ".features.tmp")
    output_file = destination.with_name(destination.name + ".tmp")
    try:
        with features_file.open("w", encoding="utf-8") as features_output:
            for kind, feature in stream_geojson(source):
                if kind == "metadata":
                    metadata = feature
                    continue
                geometry = feature.get("geometry") or {}
                if geometry.get("type") != "Point" or len(geometry.get("coordinates", [])) < 2:
                    continue
                props = feature.get("properties") or {}
                quality = classify_quality(props)
                counts[quality] += 1
                light = {name: props.get(name) for name in keep}
                light.update(quality=quality, quality_label=QUALITY_LABELS[quality])
                if mapped:
                    features_output.write(",")
                features_output.write(json.dumps({"type": "Feature", "geometry": geometry, "properties": light}, ensure_ascii=False))
                mapped += 1
        total_csv = int(metadata.get("total_registros_csv") or mapped)
        summary = {"total_records": total_csv, "mapped": mapped,
                   "without_coordinates": int(metadata.get("total_sem_coordenada") or max(total_csv-mapped, 0)),
                   "quality": counts}
        header = {"type": "FeatureCollection", "metadata": summary}
        with output_file.open("w", encoding="utf-8") as output, features_file.open("r", encoding="utf-8") as features_input:
            output.write(json.dumps(header, ensure_ascii=False)[:-1] + ', "features": [')
            shutil.copyfileobj(features_input, output, length=1024 * 1024)
            output.write("]}")
        output_file.replace(destination)
        return summary
    finally:
        features_file.unlink(missing_ok=True)
        output_file.unlink(missing_ok=True)


class GeocodingBridge:
    def __init__(self, data_dir: Path, processor: MunicipalProcessor, api_url: str, project_dir: Path | None = None, store=None):
        self.processor = processor
        self.api_url = api_url.rstrip("/")
        self.project_dir = project_dir
        self.store = store
        self.jobs_dir = data_dir / "geocodificacoes"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id): return self.jobs_dir / job_id / "status.json"

    def _save(self, state):
        state["updated_at"] = now_iso(); path = self._path(state["job_id"]); path.parent.mkdir(parents=True, exist_ok=True)
        if self.store: self.store.put_operation("geocoding", state["job_id"], state, path)
        temp = path.with_suffix(".json.tmp")
        for attempt in range(6):
            try: temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"); temp.replace(path); return
            except PermissionError:
                if attempt == 5: raise
                time.sleep(.03 * (attempt + 1))

    def get(self, job_id):
        if self.store:
            stored = self.store.get_operation("geocoding", job_id)
            if stored is not None: return stored
        path = self._path(job_id)
        if not path.exists(): raise KeyError(job_id)
        for attempt in range(6):
            try: return json.loads(path.read_text(encoding="utf-8"))
            except (PermissionError, json.JSONDecodeError):
                if attempt == 5: raise
                time.sleep(.03 * (attempt + 1))

    def list(self):
        if self.store: return self.store.list_operations("geocoding")
        result = []
        for path in self.jobs_dir.glob("*/status.json"):
            try: result.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError): pass
        return sorted(result, key=lambda item: item.get("created_at", ""), reverse=True)

    def start_service(self):
        health = self.health()
        if health.get("online") and health.get("ok"):
            return {"ok": True, "already_running": True, "message": health.get("message")}
        raise RuntimeError("O motor Python está integrado ao GeoCNPJ, mas não respondeu: " + health.get("message", "sem resposta"))

    def health(self):
        try:
            response = requests.post(self.api_url + "/check-python", timeout=15); response.raise_for_status()
            data = response.json(); return {"online": True, **data, "api_url": self.api_url}
        except Exception as exc: return {"online": False, "ok": False, "message": str(exc), "api_url": self.api_url}

    def artifacts(self):
        result = []
        for job in self.processor.list():
            if job.get("status") != "completed": continue
            try: path = self.processor.output_path(job["job_id"])
            except Exception: continue
            result.append({"process_job_id": job["job_id"], "competence": job["competence"], "uf": job["uf"],
                           "municipality_name": job["municipality_name"], "rows": job["rows_found"],
                           "filename": path.name, "size": path.stat().st_size,
                           "is_partial": job.get("is_partial", False),
                           "parts_used": len(job.get("source_files", [])),
                           "parts_official": job.get("official_file_count", len(job.get("source_files", [])))})
        return result

    def create(self, process_job_id: str, output_format="csv", cores=1, resolve_ties=True):
        source = self.processor.output_path(process_job_id)
        source_job = self.processor.get(process_job_id)
        job_id = uuid.uuid4().hex[:10]
        state = {"job_id": job_id, "status": "queued", "process_job_id": process_job_id,
                 "competence": source_job["competence"], "municipality_name": source_job["municipality_name"],
                 "is_partial": source_job.get("is_partial", False),
                 "parts_used": len(source_job.get("source_files", [])),
                 "parts_official": source_job.get("official_file_count", len(source_job.get("source_files", []))),
                 "input_file": source.name, "output_format": output_format, "cores": max(1, int(cores)),
                 "resolve_ties": bool(resolve_ties), "percent": 0, "message": "Envio para geocodificação na fila.",
                 "created_at": now_iso(), "logs": [], "can_cancel": True}
        self._save(state); threading.Thread(target=self._run, args=(job_id, source), daemon=True).start(); return state

    def _run(self, job_id, source):
        state = self.get(job_id)
        try:
            health = self.health()
            if not health.get("online") or not health.get("ok"): raise RuntimeError("Python/geocodebr indisponível: " + health.get("message", "sem resposta"))
            if self.get(job_id).get("status") == "cancelled": return
            state.update(status="uploading", percent=2, started_at=now_iso(), message="Enviando a base preparada ao módulo de geocodificação."); self._save(state)
            with source.open("rb") as handle:
                response = requests.post(self.api_url + "/jobs", files={"arquivo": (source.name, handle, "application/octet-stream")},
                    data={"formato_saida": state["output_format"], "n_cores": state["cores"],
                          "resolver_empates": str(state["resolve_ties"]).lower()}, timeout=(30, 600))
            response.raise_for_status(); remote = response.json(); state["remote_job_id"] = remote["job_id"]
            if self.get(job_id).get("status") == "cancelled":
                requests.post(f"{self.api_url}/jobs/{remote['job_id']}/cancel", timeout=25).raise_for_status()
                return
            state.update(status="running", percent=5, message="Geocodificação iniciada."); self._save(state)
            while True:
                response = requests.get(f"{self.api_url}/jobs/{state['remote_job_id']}", timeout=30); response.raise_for_status(); remote_state = response.json()
                remote_status = remote_state.get("status", "running")
                state["remote_status"] = remote_status; state["remote"] = remote_state
                state["stage"] = remote_state.get("stage")
                state["logs"] = (remote_state.get("logs") or [])[-30:]
                state["message"] = (state["logs"][-1] if state["logs"] else remote_state.get("status_label")) or remote_status
                state["percent"] = remote_state.get("percentual") or (100 if remote_status == "completed" else 0)
                if remote_status == "cancelled":
                    state.update(status="cancelled", can_cancel=False, finished_at=now_iso(), message="Geocodificação interrompida pelo usuário.")
                    self._save(state); return
                if self.get(job_id).get("status") == "cancelling":
                    state["status"] = "cancelling"
                    state["can_cancel"] = False
                if remote_status == "completed":
                    state.update(percent=98, can_cancel=False, message="Preparando pacote e mapa local.", remote_download_url=remote_state.get("download_url")); self._save(state)
                    self._cache_outputs(state)
                    state.update(status="completed", percent=100, can_cancel=False, finished_at=now_iso(), message="Geocodificação concluída.",
                                 download_url=f"/api/geocoding/{job_id}/download", map_url=f"/map?job={job_id}", map_data_url=f"/api/geocoding/{job_id}/map-data")
                    self._save(state); return
                if remote_status == "error": raise RuntimeError(state["message"])
                self._save(state); time.sleep(2)
        except Exception as exc:
            state.update(status="error", can_cancel=False, finished_at=now_iso(), message=str(exc)); self._save(state)

    def restart(self, job_id):
        state = self.get(job_id)
        if state.get("status") not in {"interrupted", "error", "cancelled"}:
            raise ValueError("Esta geocodificação não pode ser reiniciada.")
        for key in ("remote_job_id", "remote_status", "remote", "remote_download_url"):
            state.pop(key, None)
        state.update(status="queued", percent=0, can_cancel=True, stage=None, message="Geocodificação reiniciada com os mesmos parâmetros.")
        self._save(state)
        source = self.processor.output_path(state["process_job_id"])
        threading.Thread(target=self._run, args=(job_id, source), daemon=True).start()
        return state

    def cancel(self, job_id):
        state = self.get(job_id)
        if state.get("status") in {"completed", "cancelled", "error"}:
            return state
        remote_id = state.get("remote_job_id")
        if remote_id:
            response = requests.post(f"{self.api_url}/jobs/{remote_id}/cancel", timeout=25)
            response.raise_for_status()
            remote = response.json()
            state["remote"] = remote
            state["status"] = "cancelled" if remote.get("status") == "cancelled" else "cancelling"
        else:
            state["status"] = "cancelled"
        state["can_cancel"] = False
        state["message"] = "Interrupção solicitada. Os arquivos já criados serão preservados."
        if state["status"] == "cancelled": state["finished_at"] = now_iso()
        self._save(state)
        return state

    def _cache_outputs(self, state):
        if not state.get("remote_download_url"): raise RuntimeError("Módulo GEO não informou o pacote final.")
        job_dir = self._path(state["job_id"]).parent; package = job_dir / "pacote_geocodificado.zip"
        response = requests.get(self.api_url + state["remote_download_url"], stream=True, timeout=(30, 600)); response.raise_for_status()
        with package.open("wb") as output:
            for chunk in response.iter_content(1024 * 1024):
                if chunk: output.write(chunk)
        with zipfile.ZipFile(package) as archive:
            candidates = [m for m in archive.infolist() if not m.is_dir() and m.filename.lower().endswith(".geojson")]
            if not candidates: raise RuntimeError("O pacote geocodificado não contém GeoJSON.")
            raw = job_dir / "resultado_completo.geojson"
            with archive.open(candidates[0]) as source, raw.open("wb") as output:
                while chunk := source.read(1024 * 1024): output.write(chunk)
        light = job_dir / "mapa_qualidade.geojson"; state["map_summary"] = prepare_map_geojson(raw, light)
        state["package_file"] = str(package); state["map_file"] = str(light)

    def download_path(self, job_id):
        state = self.get(job_id)
        if state.get("status") != "completed" or not state.get("package_file"):
            raise ValueError("A geocodificação ainda não possui pacote final.")
        path = Path(state["package_file"])
        if not path.exists(): raise FileNotFoundError(path)
        return path

    def map_path(self, job_id):
        state = self.get(job_id); value = state.get("map_file")
        if not value: raise ValueError("O mapa ainda não está disponível.")
        path = Path(value)
        if state.get("status") != "completed" or not path.is_file(): raise ValueError("O mapa ainda não está disponível.")
        return path

    def full_map_path(self, job_id):
        light = self.map_path(job_id)
        full = light.with_name("resultado_completo.geojson")
        return full if full.is_file() else light
