from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, RedirectResponse

from ..dependencies import get_settings

router = APIRouter()


def page(filename):
    def response(settings=Depends(get_settings)):
        return FileResponse(settings.frontend_dir / filename)
    return response


router.add_api_route("/", page("home.html"), methods=["GET"])
router.add_api_route("/projects", page("projects.html"), methods=["GET"])
router.add_api_route("/collection", page("collection.html"), methods=["GET"])
@router.get("/operations", include_in_schema=False)
def legacy_operations():
    return RedirectResponse("/collection#operations", status_code=307)
router.add_api_route("/pipeline", page("index.html"), methods=["GET"])
router.add_api_route("/etapas", page("index.html"), methods=["GET"])
router.add_api_route("/map", page("map.html"), methods=["GET"])
router.add_api_route("/metodologia", page("metodologia.html"), methods=["GET"])
