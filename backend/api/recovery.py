import os

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import get_services

router = APIRouter(prefix="/api", tags=["recuperação"])


@router.get("/system/database")
def database(s=Depends(get_services)):
    return {**s.store.diagnostics(), "migration": s.migration_result,
            "interrupted_on_startup": s.abandoned_on_startup}


@router.get("/recovery")
def recoveries(s=Depends(get_services)): return s.store.recoverable()


@router.get("/integrity")
def integrity(include_ignored: bool = False, s=Depends(get_services)):
    return s.store.scan_orphans(s.projects.list(), include_ignored)


@router.post("/integrity/{orphan_id}/{action}")
def integrity_action(orphan_id: str, action: str, s=Depends(get_services)):
    try: return s.store.handle_orphan(orphan_id, action, s.projects.list())
    except KeyError as exc: raise HTTPException(404, "Ocorrência não encontrada ou já resolvida.") from exc
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc


@router.get("/recovery/{kind}/{operation_id}")
def details(kind: str, operation_id: str, s=Depends(get_services)):
    operation = s.store.get_operation(kind, operation_id)
    if operation is None: raise HTTPException(404, "Execução não encontrada.")
    return operation


@router.post("/recovery/{kind}/{operation_id}/{action}")
def action(kind: str, operation_id: str, action: str, s=Depends(get_services)):
    try:
        manager = {"download": s.downloads, "process": s.processor, "geocoding": s.geocoder}.get(kind)
        if action == "continue" and kind in {"download", "process"}: return manager.resume(operation_id)
        if action == "restart" and manager:
            return manager.restart(operation_id) if kind == "geocoding" else manager.resume(operation_id)
        if action == "cancel":
            if manager: return manager.cancel(operation_id)
            operation = s.store.get_operation(kind, operation_id)
            operation.update(status="cancelled", message="Execução cancelada pelo usuário.")
            s.store.put_operation(kind, operation_id, operation, reason="Cancelamento manual")
            return operation
        raise ValueError("Ação de recuperação inválida ou retomada não segura para esta etapa.")
    except KeyError as exc: raise HTTPException(404, "Execução não encontrada.") from exc
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc
    except RuntimeError as exc: raise HTTPException(409, str(exc)) from exc


@router.post("/system/select-folder")
def select_folder():
    if os.name != "nt": raise HTTPException(501, "O seletor nativo está disponível apenas no Windows.")
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title="Selecione uma pasta para o GeoCNPJ")
        root.destroy()
        return {"path": selected or None}
    except Exception as exc: raise HTTPException(500, f"Não foi possível abrir o seletor de pastas: {exc}") from exc
