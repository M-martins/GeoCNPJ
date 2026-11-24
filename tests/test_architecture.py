import unittest
from pathlib import Path


class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent.parent

    def test_main_only_exposes_application_factory(self):
        main = (self.root / "backend" / "main.py").read_text(encoding="utf-8")
        self.assertIn("create_app", main)
        self.assertNotIn("migrate_json_controls", main)
        self.assertNotIn("mark_abandoned", main)
        self.assertLessEqual(len(main.splitlines()), 5)

    def test_backend_is_split_by_domain(self):
        api = self.root / "backend" / "api"
        for name in ("projects", "downloads", "processing", "geocoding", "collection",
                     "recovery", "dashboard", "pages", "router"):
            self.assertTrue((api / f"{name}.py").exists(), name)
        for name in ("application.py", "config.py", "dependencies.py", "models.py",
                     "services.py", "repositories.py"):
            self.assertTrue((self.root / "backend" / name).exists(), name)

    def test_startup_work_is_inside_lifespan(self):
        application = (self.root / "backend" / "application.py").read_text(encoding="utf-8")
        services = (self.root / "backend" / "services.py").read_text(encoding="utf-8")
        self.assertIn("async def lifespan", application)
        self.assertIn("active_services.startup()", application)
        self.assertIn("self.store.migrate_json_controls()", services)
        self.assertIn("self.store.mark_abandoned()", services)
        self.assertIn("active_services.shutdown()", application)
        self.assertIn("renew_owned_leases", services)
        self.assertIn("self.auto_resume", services)

    def test_dashboard_endpoints_are_consolidated(self):
        dashboard = (self.root / "backend" / "api" / "dashboard.py").read_text(encoding="utf-8")
        ui = (self.root / "frontend" / "assets" / "ui.js").read_text(encoding="utf-8")
        collection = (self.root / "frontend" / "assets" / "collection.js").read_text(encoding="utf-8")
        self.assertIn('@router.get("/dashboard")', dashboard)
        self.assertIn('@router.get("/collection/dashboard")', dashboard)
        self.assertIn("request('/api/dashboard')", ui)
        self.assertIn("request('/api/collection/dashboard')", collection)


if __name__ == "__main__": unittest.main()
