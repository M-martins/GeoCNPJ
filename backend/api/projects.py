from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import get_services
from ..models import ProjectRequest, ReviewRequest

router = APIRouter(prefix="/api", tags=["projetos"])


@router.get("/projects")
def list_projects(s=Depends(get_services)): return s.projects.list()


@router.post("/projects")
def create_project(request: ProjectRequest, s=Depends(get_services)):
    try: return s.projects.create(request.name, request.competence)
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.get("/projects/{project_id}")
def get_project(project_id: str, s=Depends(get_services)):
    try: return s.projects.get(project_id)
    except KeyError as exc: raise HTTPException(404, "Projeto não encontrado.") from exc


@router.post("/projects/{project_id}/select-month/{competence}")
def select_project_month(project_id: str, competence: str, s=Depends(get_services)):
    try: return s.projects.select_competence(project_id, competence)
    except KeyError as exc: raise HTTPException(404, "Projeto não encontrado.") from exc
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc


@router.post("/projects/{project_id}/duplicate")
def duplicate_project(project_id: str, s=Depends(get_services)):
    try: return s.projects.duplicate(project_id)
    except KeyError as exc: raise HTTPException(404, "Projeto não encontrado.") from exc


@router.post("/projects/{project_id}/attach-process/{job_id}")
def attach_process(project_id: str, job_id: str, s=Depends(get_services)):
    try:
        process = s.processor.get(job_id)
        if process.get("status") != "completed": raise ValueError("A base municipal ainda não foi concluída.")
        s.projects.attach_process(project_id, process)
        return s.projects.get(project_id)
    except KeyError as exc: raise HTTPException(404, "Projeto ou base municipal não encontrado.") from exc
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc


@router.post("/projects/{project_id}/attach-geocoding/{job_id}")
def attach_geocoding(project_id: str, job_id: str, s=Depends(get_services)):
    try:
        item = s.geocoder.get(job_id)
        if item.get("status") != "completed": raise ValueError("A geocodificação ainda não foi concluída.")
        s.projects.attach_geocoding(project_id, item)
        return s.projects.get(project_id)
    except KeyError as exc: raise HTTPException(404, "Projeto ou geocodificação não encontrado.") from exc
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc


@router.get("/reuse/matches")
def reuse_matches(competence: str, uf: str, municipality_code: str, active_only: bool = True,
                  output_format: str = "csv", s=Depends(get_services)):
    return s.projects.reuse_matches(competence, uf, municipality_code, active_only, output_format)


@router.patch("/projects/{project_id}")
def rename_project(project_id: str, request: ProjectRequest, s=Depends(get_services)):
    try: return s.projects.rename(project_id, request.name)
    except KeyError as exc: raise HTTPException(404, "Projeto não encontrado.") from exc
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.get("/projects/{project_id}/reviews")
def reviews(project_id: str, s=Depends(get_services)):
    try: return s.projects.reviews(project_id)
    except KeyError as exc: raise HTTPException(404, "Projeto não encontrado.") from exc


@router.put("/projects/{project_id}/reviews/{cnpj}")
def set_review(project_id: str, cnpj: str, request: ReviewRequest, s=Depends(get_services)):
    try: return s.projects.set_review(project_id, cnpj, request.reviewed, request.note)
    except KeyError as exc: raise HTTPException(404, "Projeto não encontrado.") from exc
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@router.delete("/projects/{project_id}")
def remove_project(project_id: str, s=Depends(get_services)):
    try: return s.projects.remove(project_id)
    except KeyError as exc: raise HTTPException(404, "Projeto não encontrado.") from exc
