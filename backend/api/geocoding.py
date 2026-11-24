from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
import csv
import io
import json
from itertools import chain
from urllib.parse import quote

from ..dependencies import get_services
from ..models import GeocodingRequest

router = APIRouter(prefix="/api/geocoding", tags=["geocodificação"])


def query_filters(qualities=None, cnpj=None, name=None, street=None, number=None, neighborhood=None,
                  score_min=None, score_max=None, precision=None, decision=None, selected=None,
                  cnae=None, activity=None):
    filters = {k: v for k, v in locals().items() if v not in (None, "")}
    for key, value in filters.items():
        if isinstance(value, str) and len(value) > (7500 if key == "selected" else 160):
            raise HTTPException(422, f"Filtro {key} excede o tamanho permitido.")
    if selected and len(selected.split(",")) > 500:
        raise HTTPException(422, "Selecione no máximo 500 registros por exportação.")
    return filters


def safe_csv_cell(value):
    """Keep spreadsheet programs from interpreting untrusted text as a formula."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


@router.get("/health")
def health(s=Depends(get_services)): return s.geocoder.health()


@router.post("/start-service")
def start_service(s=Depends(get_services)):
    try: return s.geocoder.start_service()
    except Exception as exc: raise HTTPException(500, str(exc)) from exc


@router.get("/artifacts")
def artifacts(s=Depends(get_services)): return s.geocoder.artifacts()


@router.post("")
def create(request: GeocodingRequest, s=Depends(get_services)):
    try:
        result = s.geocoder.create(request.process_job_id, request.output_format,
                                   request.cores, request.resolve_ties)
        s.projects.attach_geocoding(request.project_id, result)
        return result
    except RuntimeError as exc: raise HTTPException(409, str(exc)) from exc
    except (KeyError, ValueError, FileNotFoundError) as exc: raise HTTPException(400, str(exc)) from exc


@router.get("")
def list_items(s=Depends(get_services)): return s.geocoder.list()


@router.get("/{job_id}")
def status(job_id: str, s=Depends(get_services)):
    try: return s.geocoder.get(job_id)
    except KeyError as exc: raise HTTPException(404, "Geocodificação não encontrada.") from exc


@router.post("/{job_id}/cancel")
def cancel(job_id: str, s=Depends(get_services)):
    try: return s.geocoder.cancel(job_id)
    except KeyError as exc: raise HTTPException(404, "Geocodificação não encontrada.") from exc
    except Exception as exc: raise HTTPException(409, str(exc)) from exc


@router.get("/{job_id}/download")
def download(job_id: str, s=Depends(get_services)):
    try:
        path = s.geocoder.download_path(job_id)
        return FileResponse(path, filename=f"geocodificacao_{job_id}.zip", media_type="application/zip")
    except KeyError as exc: raise HTTPException(404, "Geocodificação não encontrada.") from exc
    except Exception as exc: raise HTTPException(409, str(exc)) from exc


@router.get("/{job_id}/map-data")
def map_data(job_id: str, s=Depends(get_services)):
    try: return FileResponse(s.geocoder.map_path(job_id), media_type="application/geo+json")
    except KeyError as exc: raise HTTPException(404, "Geocodificação não encontrada.") from exc
    except Exception as exc: raise HTTPException(409, str(exc)) from exc


@router.get("/{job_id}/map/summary")
def map_summary(job_id: str, s=Depends(get_services)):
    try: return s.map_index.summary(job_id)
    except (KeyError, ValueError, FileNotFoundError) as exc: raise HTTPException(404, str(exc)) from exc


@router.get("/{job_id}/map/viewport")
def map_viewport(job_id: str, west: float, south: float, east: float, north: float, zoom: float,
                 qualities: str | None = None, cnpj: str | None = None, name: str | None = None,
                 street: str | None = None, number: str | None = None, neighborhood: str | None = None,
                 score_min: float | None = None, score_max: float | None = None,
                 precision: str | None = None, decision: str | None = None, project_id: str | None = None,
                 review_state: str | None = None, cnae: str | None = None, activity: str | None = None,
                 s=Depends(get_services)):
    reviewed=set((s.projects.reviews(project_id).get("records") or {}).keys()) if project_id and review_state else set()
    return s.map_index.viewport(job_id, (west,south,east,north), zoom,
        query_filters(qualities,cnpj,name,street,number,neighborhood,score_min,score_max,precision,decision,cnae=cnae,activity=activity),reviewed,review_state)


@router.get("/{job_id}/map/records")
def map_records(job_id: str, page: int = 1, page_size: int = 120, qualities: str | None = None,
                cnpj: str | None = None, name: str | None = None, street: str | None = None,
                number: str | None = None, neighborhood: str | None = None, score_min: float | None = None,
                score_max: float | None = None, precision: str | None = None, decision: str | None = None,
                project_id: str | None = None, review_state: str | None = None,
                cnae: str | None = None, activity: str | None = None,
                s=Depends(get_services)):
    if page < 1 or page > 1_000_000:
        raise HTTPException(422, "Pagina fora do intervalo permitido.")
    reviewed=set((s.projects.reviews(project_id).get("records") or {}).keys()) if project_id and review_state else set()
    return s.map_index.records(job_id,
        query_filters(qualities,cnpj,name,street,number,neighborhood,score_min,score_max,precision,decision,cnae=cnae,activity=activity),
        max(1,page), min(500,max(1,page_size)),reviewed,review_state)


@router.get("/{job_id}/map/suggestions")
def map_suggestions(job_id: str, field: str, q: str, s=Depends(get_services)):
    if field not in {"cnpj","name","street","activity"}: raise HTTPException(400,"Campo de sugestão inválido.")
    if len(q) > 160: raise HTTPException(422, "Busca muito longa.")
    return s.map_index.suggestions(job_id, field, q)


@router.get("/{job_id}/map/records/{cnpj}")
def map_record_detail(job_id: str, cnpj: str, s=Depends(get_services)):
    feature=s.map_index.detail(job_id,cnpj)
    if feature is None: raise HTTPException(404,"Estabelecimento não encontrado.")
    return feature


@router.get("/{job_id}/map/export")
def map_export(job_id: str, format: str = "csv", qualities: str | None = None, cnpj: str | None = None,
               name: str | None = None, street: str | None = None, number: str | None = None,
               neighborhood: str | None = None, score_min: float | None = None, score_max: float | None = None,
               precision: str | None = None, decision: str | None = None, selected: str | None = None,
               project_id: str | None = None, review_state: str | None = None,
               cnae: str | None = None, activity: str | None = None,
               s=Depends(get_services)):
    filters=query_filters(qualities,cnpj,name,street,number,neighborhood,score_min,score_max,precision,decision,selected,cnae,activity)
    review_records=(s.projects.reviews(project_id).get("records") or {}) if project_id else {}
    reviewed={cnpj for cnpj,value in review_records.items() if value.get("reviewed")}
    def selected_features():
        for feature in s.map_index.iter_features(job_id,filters):
            is_reviewed=str(feature["properties"].get("cnpj_completo")) in reviewed
            if review_state and (review_state == "reviewed") != is_reviewed: continue
            feature["properties"]["revisado"]=is_reviewed
            yield feature
    features=selected_features()
    if format == "geojson":
        def geojson_stream():
            yield '{"type":"FeatureCollection","features":['; first=True
            for feature in features:
                if not first: yield ','
                first=False; yield json.dumps(feature,ensure_ascii=False,separators=(",",":"))
            yield ']}'
        return StreamingResponse(geojson_stream(),media_type="application/geo+json",headers={"Content-Disposition":f'attachment; filename="geocnpj_{job_id}.geojson"'})
    def csv_stream():
        first=next(features,None)
        if first is None: yield '\ufeff'; return
        columns=list(first["properties"].keys())
        for column in ("latitude","longitude"):
            if column not in columns: columns.append(column)
        buffer=io.StringIO(); writer=csv.DictWriter(buffer,fieldnames=columns,delimiter=";",extrasaction="ignore"); writer.writeheader(); yield '\ufeff'+buffer.getvalue(); buffer.seek(0);buffer.truncate(0)
        for feature in chain([first],features):
            p=dict(feature["properties"]);p["longitude"],p["latitude"]=feature["geometry"]["coordinates"];writer.writerow({key: safe_csv_cell(value) for key, value in p.items()});yield buffer.getvalue();buffer.seek(0);buffer.truncate(0)
    return StreamingResponse(csv_stream(),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="geocnpj_{job_id}.csv"'})
