from dataclasses import dataclass
import threading

from .catalog import ReceitaCatalog
from .downloader import DownloadManager
from .geocoder import GeocodingBridge
from .processor import MunicipalProcessor
from .projects import ProjectManager
from .storage import StorageLibrary
from .repositories import OperationalRepository
from .map_index import MapIndex


@dataclass
class Services:
    catalog: ReceitaCatalog
    store: OperationalRepository
    library: StorageLibrary
    downloads: DownloadManager
    processor: MunicipalProcessor
    geocoder: GeocodingBridge
    projects: ProjectManager
    map_index: MapIndex | None = None
    migration_result: dict | None = None
    abandoned_on_startup: int | list | dict | None = None
    auto_resume: bool = False
    _stop: threading.Event | None = None
    _heartbeat_thread: threading.Thread | None = None

    @classmethod
    def build(cls, settings):
        catalog = ReceitaCatalog(settings.webdav_url, settings.share_token)
        store = OperationalRepository(settings.data_dir, lease_seconds=settings.lease_seconds)
        library = StorageLibrary(settings.data_dir, store)
        processor = MunicipalProcessor(settings.data_dir, catalog, library, store)
        geocoder = GeocodingBridge(settings.data_dir, processor, settings.geo_api_url,
                                   settings.geo_project_dir, store)
        downloads = DownloadManager(settings.data_dir, catalog, library, store)
        projects = ProjectManager(settings.data_dir, library, processor, geocoder, store)
        return cls(catalog, store, library, downloads, processor, geocoder, projects,
                   map_index=MapIndex(geocoder), auto_resume=settings.auto_resume)

    def startup(self):
        self.migration_result = self.store.migrate_json_controls()
        self.abandoned_on_startup = self.store.mark_abandoned()
        self._stop = threading.Event()
        interval = max(5, self.store.lease_seconds // 3)
        self._heartbeat_thread = threading.Thread(target=self._heartbeat, args=(interval,), daemon=True)
        self._heartbeat_thread.start()
        if self.auto_resume:
            for item in self.abandoned_on_startup:
                try:
                    manager = {"download": self.downloads, "process": self.processor,
                               "geocoding": self.geocoder}.get(item["kind"])
                    if manager:
                        manager.restart(item["operation_id"]) if item["kind"] == "geocoding" else manager.resume(item["operation_id"])
                except (KeyError, ValueError, RuntimeError):
                    pass

    def _heartbeat(self, interval):
        while not self._stop.wait(interval):
            self.store.renew_owned_leases()

    def shutdown(self):
        if self._stop: self._stop.set()
        for item in self.store.owned_active():
            manager = {"download": self.downloads, "process": self.processor,
                       "geocoding": self.geocoder}.get(item["kind"])
            try:
                if manager: manager.cancel(item["operation_id"])
            except (KeyError, ValueError):
                pass
        interrupted = self.store.interrupt_owned()
        if self._heartbeat_thread: self._heartbeat_thread.join(timeout=2)
        return interrupted
