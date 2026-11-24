from fastapi import APIRouter, Depends

from ..dependencies import get_services

router = APIRouter(prefix="/api", tags=["painel"])


def snapshot(s):
    project_rows = s.projects.list()
    recoveries = s.store.recoverable()
    integrity = s.store.scan_orphans(project_rows, False)
    return project_rows, recoveries, integrity


@router.get("/dashboard")
def dashboard(s=Depends(get_services)):
    projects, recoveries, integrity = snapshot(s)
    return {"projects": projects, "recoveries": recoveries, "integrity": integrity}


@router.get("/collection/dashboard")
def collection_dashboard(s=Depends(get_services)):
    projects, recoveries, integrity = snapshot(s)
    processes = s.processor.list()
    geocodings = s.geocoder.list()
    readiness = s.processor.readiness()
    ready = set(readiness["ready_competences"])
    overview = s.library.storage_overview(processes, geocodings, projects, ready)
    return {
        "library": s.library.inventory(ready), "processes": processes,
        "geocodings": geocodings, "projects": projects, "overview": overview,
        "recoveries": recoveries, "integrity": integrity, "readiness": readiness,
    }
