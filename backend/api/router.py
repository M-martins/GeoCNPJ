from fastapi import APIRouter

from . import collection, dashboard, downloads, geocoding, pages, processing, projects, recovery

page_router = pages.router
api_router = APIRouter()
for router in (projects.router, downloads.router, processing.router, geocoding.router,
               collection.router, recovery.router, dashboard.router):
    api_router.include_router(router)
