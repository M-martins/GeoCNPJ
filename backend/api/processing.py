from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..dependencies import get_services
from ..models import ProcessRequest

router = APIRouter(prefix="/api", tags=["processamento"])


@router.get("/process/readiness")
def readiness(s=Depends(get_services)): return s.processor.readiness()


@router.post("/process/validate/{competence}")
def validate(competence: str, s=Depends(get_services)):
    try: return s.processor.start_validation(competence)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc: raise HTTPException(409, str(exc)) from exc
    except Exception as exc: raise HTTPException(502, f"Falha ao validar os dados do mês: {exc}") from exc


@router.get("/process/validation/{validation_id}")
def validation(validation_id: str, s=Depends(get_services)):
    try: return s.processor.get_validation(validation_id)
    except KeyError as exc: raise HTTPException(404, "Validação não encontrada.") from exc


@router.get("/municipalities")
def municipalities(q: str = "", uf: str = "", s=Depends(get_services)):
    try: return s.processor.references.municipalities(q, uf)
    except FileNotFoundError as exc: raise HTTPException(409, str(exc)) from exc


@router.get("/processes")
def list_processes(s=Depends(get_services)): return s.processor.list()


@router.post("/processes")
def create_process(request: ProcessRequest, s=Depends(get_services)):
    try:
        result = s.processor.create(request.competence, request.uf, request.municipality_code,
                                    request.municipality_name, request.active_only, request.output_format,
                                    accept_incomplete=request.accept_incomplete)
        s.projects.attach_process(request.project_id, result)
        return result
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc: raise HTTPException(409, str(exc)) from exc


@router.get("/processes/{job_id}")
def get_process(job_id: str, s=Depends(get_services)):
    try: return s.processor.get(job_id)
    except KeyError as exc: raise HTTPException(404, "Processamento não encontrado.") from exc


@router.post("/processes/{job_id}/cancel")
def cancel_process(job_id: str, s=Depends(get_services)):
    try: return s.processor.cancel(job_id)
    except KeyError as exc: raise HTTPException(404, "Processamento não encontrado.") from exc


@router.get("/processes/{job_id}/download")
def download_process(job_id: str, s=Depends(get_services)):
    try:
        path = s.processor.output_path(job_id)
        return FileResponse(path, filename=path.name)
    except KeyError as exc: raise HTTPException(404, "Processamento não encontrado.") from exc
    except (ValueError, FileNotFoundError) as exc: raise HTTPException(409, str(exc)) from exc
