import tempfile
import unittest
from pathlib import Path

from backend.projects import ProjectManager


class StubProcessor:
    def readiness(self): return {"ready_competences": ["2026-07"]}
    def list(self): return [{"job_id": "process1", "status": "completed", "competence": "2026-07", "uf": "SP", "municipality_code": "6713", "municipality_name": "MOGI DAS CRUZES", "active_only": True, "rows_found": 72890, "created_at": "2026-08-02T10:00:00-03:00", "updated_at": "2026-08-02T11:00:00-03:00"}]


class StubGeocoder:
    def list(self): return [{"job_id": "geo1", "process_job_id": "process1", "status": "completed", "map_url": "/map?job=geo1", "map_summary": {"mapped": 72890}, "updated_at": "2026-08-02T12:00:00-03:00"}]


class StubEmptyGeocoder:
    def list(self): return []


class ProjectTests(unittest.TestCase):
    def test_partial_result_is_not_offered_after_more_parts_are_downloaded(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            month = folder / "competencias" / "2026-07"
            month.mkdir(parents=True)
            for index in (0, 1): (month / f"Estabelecimentos{index}.zip").touch()

            class Processor(StubProcessor):
                def __init__(self): self.library = type("Library", (), {"path": lambda self, competence: month})()
                def list(self):
                    return [{**super().list()[0], "is_partial": True,
                             "source_files": ["Estabelecimentos0.zip", "Estabelecimentos1.zip"],
                             "official_file_count": 10}]

            manager = ProjectManager(folder, object(), Processor(), StubEmptyGeocoder())
            self.assertEqual(len(manager.reuse_matches("2026-07", "SP", "6713")), 1)
            self.assertTrue(manager.list()[0]["coverage"]["is_partial"])
            (month / "Estabelecimentos2.zip").touch()
            self.assertEqual(manager.reuse_matches("2026-07", "SP", "6713"), [])

    def test_removed_month_files_do_not_complete_data_step(self):
        project = {"competence": "2026-11", "process_job_id": "partial"}
        readiness = {"ready_competences": [], "competences": [{"competence": "2026-11", "present": 0}], "references_complete": True}
        processes = [{"job_id": "partial", "status": "completed", "is_partial": True, "rows_found": 10}]
        enriched = ProjectManager._enrich(None, project, readiness, processes, [])
        self.assertEqual(enriched["steps"]["data"]["status"], "pending")
        self.assertEqual(enriched["steps"]["preparation"]["status"], "completed")

    def test_discovers_and_persists_existing_project(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = ProjectManager(Path(folder), object(), StubProcessor(), StubGeocoder())
            first = manager.list(); second = manager.list()
            self.assertEqual(len(first), 1); self.assertEqual(len(second), 1)
            self.assertEqual(first[0]["steps"]["review"]["status"], "available")
            self.assertTrue((Path(folder) / "controle" / "projetos.json").exists())

    def test_duplicate_and_remove_preserve_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = ProjectManager(Path(folder), object(), StubProcessor(), StubGeocoder())
            original = manager.list()[0]; duplicate = manager.duplicate(original["project_id"])
            self.assertEqual(len(manager.list()), 2)
            result = manager.remove(duplicate["project_id"])
            self.assertTrue(result["files_preserved"]); self.assertEqual(len(manager.list()), 1)

    def test_removed_discovered_project_does_not_return(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = ProjectManager(Path(folder), object(), StubProcessor(), StubGeocoder())
            original = manager.list()[0]
            manager.remove(original["project_id"])
            self.assertEqual(manager.list(), [])

    def test_manual_project_can_be_created_and_renamed(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = ProjectManager(Path(folder), object(), StubProcessor(), StubGeocoder())
            project = manager.create("Análise regional")
            renamed = manager.rename(project["project_id"], "Análise regional 2026")
            self.assertEqual(renamed["name"], "Análise regional 2026")
            self.assertEqual(renamed["steps"]["preparation"]["status"], "pending")

    def test_review_state_is_persisted_by_cnpj(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = ProjectManager(Path(folder), object(), StubProcessor(), StubGeocoder())
            project = manager.list()[0]
            manager.set_review(project["project_id"], "12.345.678/0001-90", True, "Conferido")
            record = manager.reviews(project["project_id"])["records"]["12345678000190"]
            self.assertTrue(record["reviewed"]); self.assertEqual(record["note"], "Conferido")

    def test_existing_process_is_attached_only_when_requested(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = ProjectManager(Path(folder), object(), StubProcessor(), StubGeocoder())
            manual = manager.create("Projeto vazio")
            self.assertIsNone(manual.get("process_job_id"))
            manager.attach_process(manual["project_id"], StubProcessor().list()[0])
            attached = manager.get(manual["project_id"])
            self.assertEqual(attached["process_job_id"], "process1")
            self.assertEqual(attached["municipality_name"], "MOGI DAS CRUZES")
            self.assertIsNone(attached.get("geocoding_job_id"))
            self.assertEqual(attached["steps"]["geocoding"]["status"], "available")
            self.assertEqual(attached["processing_seconds"], 3600)

    def test_reuse_match_reports_highest_completed_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = ProjectManager(Path(folder), object(), StubProcessor(), StubGeocoder())
            match = manager.reuse_matches("2026-07", "SP", "6713", True, "csv")[0]
            self.assertEqual(match["stage"], "geocoded")
            self.assertEqual(match["geocodings"][0]["job_id"], "geo1")
        with tempfile.TemporaryDirectory() as folder:
            manager = ProjectManager(Path(folder), object(), StubProcessor(), StubEmptyGeocoder())
            match = manager.reuse_matches("2026-07", "SP", "6713", True, "csv")[0]
            self.assertEqual(match["stage"], "prepared")
            self.assertEqual(match["geocodings"], [])


if __name__ == "__main__": unittest.main()
