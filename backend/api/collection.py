from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..dependencies import get_services
from ..models import ImportRequest, RemoveRequest

router = APIRouter(prefix="/api", tags=["acervo"])


def ensure_idle(s, *, competence: str | None = None, references: bool = False, cache: bool = False):
    active = {"queued", "running", "cancelling", "uploading"}
    if not cache:
        if any(job.get("status") in active and (references or job.get("competence") == competence)
               for job in s.downloads.list()):
            raise ValueError("Há um download em andamento. Aguarde ou interrompa antes de excluir arquivos.")
        if any(job.get("status") in active and (references or job.get("competence") == competence)
               for job in s.processor.list()):
            raise ValueError("Há uma base municipal em preparação. Aguarde antes de excluir arquivos.")
    if cache and any(job.get("status") in active for job in s.geocoder.list()):
        raise ValueError("Há uma geocodificação em andamento. Aguarde antes de limpar o cache.")


@router.get("/storage")
def storage(path: str | None = None, s=Depends(get_services)): return s.library.disk_usage(path)


@router.get("/storage/overview")
def overview(s=Depends(get_services)):
    ready = set(s.processor.readiness()["ready_competences"])
    return s.library.storage_overview(s.processor.list(), s.geocoder.list(), s.projects.list(), ready)


@router.get("/library")
def inventory(s=Depends(get_services)):
    ready = set(s.processor.readiness()["ready_competences"])
    return s.library.inventory(ready)


@router.get("/library/references")
def references(s=Depends(get_services)):
    return s.library.references_inventory()


@router.get("/library/references/{name}/download")
def download_reference(name: str, s=Depends(get_services)):
    try:
        path = s.library.reference_file_path(name)
        return FileResponse(path, filename=name, media_type="text/csv" if name.endswith(".csv") else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if name.endswith(".xlsx") else "application/zip")
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc


@router.get("/library/{competence}/files/{filename}/download")
def download_local_file(competence: str, filename: str, s=Depends(get_services)):
    try:
        path = s.library.downloaded_file_path(competence, filename)
        return FileResponse(path, filename=filename, media_type="application/zip")
    except KeyError as exc: raise HTTPException(404, "Mês não registrado.") from exc
    except ValueError as exc: raise HTTPException(404, str(exc)) from exc


@router.post("/library/references/{name}/remove")
def remove_reference(name: str, s=Depends(get_services)):
    try:
        ensure_idle(s, references=True)
        return s.library.remove_reference(name)
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc


@router.post("/library/cache/remove")
def clear_geocoding_cache(s=Depends(get_services)):
    try:
        ensure_idle(s, cache=True)
        return s.library.clear_geocoding_cache()
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc


@router.post("/library/{competence}/files/{filename}/remove")
def remove_downloaded_file(competence: str, filename: str, s=Depends(get_services)):
    try:
        ensure_idle(s, competence=competence)
        return s.library.remove_downloaded_file(competence, filename)
    except KeyError as exc: raise HTTPException(404, "Mês não registrado.") from exc
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc


@router.post("/collection/artifacts/{kind}/{job_id}/remove")
def remove_completed_artifact(kind: str, job_id: str, s=Depends(get_services)):
    try:
        return s.store.remove_completed_artifact(kind, job_id, s.projects.list())
    except KeyError as exc: raise HTTPException(404, "Resultado não encontrado.") from exc
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc


@router.post("/library/import")
def import_existing(request: ImportRequest, s=Depends(get_services)):
    try:
        entry = s.library.import_folder(request.competence, request.folder)
        validation = s.processor.validate_competence(request.competence)
        return {"entry": entry, "manifest": validation}
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    except Exception as exc: raise HTTPException(502, f"Falha ao importar a pasta: {exc}") from exc


@router.post("/library/{competence}/remove")
def remove(competence: str, request: RemoveRequest, s=Depends(get_services)):
    try:
        if request.delete_files: ensure_idle(s, competence=competence)
        return s.library.remove(competence, request.delete_files)
    except KeyError as exc: raise HTTPException(404, "Mês dos dados não registrado.") from exc
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
