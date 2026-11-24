from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import get_services
from ..models import DownloadRequest

router = APIRouter(prefix="/api", tags=["downloads"])


@router.get("/catalog/competences")
def competences(s=Depends(get_services)):
    try:
        values = s.catalog.competences()
        return {"competences": values, "latest": values[0] if values else None}
    except Exception as exc: raise HTTPException(502, f"Falha ao consultar a Receita: {exc}") from exc


@router.get("/catalog/{competence}")
def files(competence: str, s=Depends(get_services)):
    try:
        values = s.catalog.files(competence)
        for item in values:
            item["local"] = s.downloads.local_state(competence, item)
        return {"competence": competence, "files": values,
                "total_bytes": sum(item["size"] or 0 for item in values)}
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    except Exception as exc: raise HTTPException(502, f"Falha ao listar os arquivos: {exc}") from exc


@router.get("/downloads")
def list_downloads(s=Depends(get_services)): return s.downloads.list()


@router.post("/downloads")
def create_download(request: DownloadRequest, s=Depends(get_services)):
    try: return s.downloads.create(request.competence, request.files, request.destination_root)
    except RuntimeError as exc: raise HTTPException(409, str(exc)) from exc
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    except Exception as exc: raise HTTPException(502, f"Falha ao criar download: {exc}") from exc


@router.get("/downloads/{job_id}")
def get_download(job_id: str, s=Depends(get_services)):
    try: return s.downloads.get(job_id)
    except KeyError as exc: raise HTTPException(404, "Download não encontrado.") from exc


@router.post("/downloads/{job_id}/cancel")
def cancel_download(job_id: str, s=Depends(get_services)):
    try: return s.downloads.cancel(job_id)
    except KeyError as exc: raise HTTPException(404, "Download não encontrado.") from exc


@router.post("/downloads/{job_id}/resume")
def resume_download(job_id: str, s=Depends(get_services)):
    try: return s.downloads.resume(job_id)
    except KeyError as exc: raise HTTPException(404, "Download não encontrado.") from exc
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc: raise HTTPException(409, str(exc)) from exc
