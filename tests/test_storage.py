import tempfile
import unittest
from pathlib import Path

from backend.storage import StorageLibrary


class StorageTests(unittest.TestCase):
    def test_external_link_is_preserved_when_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            external = root / "externa" / "2026-02"
            external.mkdir(parents=True)
            marker = external / "arquivo.zip"
            marker.write_bytes(b"teste")
            library = StorageLibrary(root / "runtime")
            library.import_folder("2026-02", str(external))
            result = library.remove("2026-02", delete_files=False)
            self.assertTrue(marker.exists())
            self.assertFalse(result["files_sent_to_trash"])

    def test_custom_destination_uses_competence_subfolder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library = StorageLibrary(root / "runtime")
            destination = library.destination("2026-07", str(root / "outro_disco"))
            self.assertEqual(destination.name, "2026-07")
            self.assertTrue(destination.exists())
            self.assertTrue(library.get("2026-07")["managed"])

    def test_overview_counts_physical_files_once_and_marks_shared_references(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "runtime"
            library = StorageLibrary(data)
            competence = library.destination("2026-07")
            (competence / "Estabelecimentos0.zip").write_bytes(b"a" * 10)
            process_dir = data / "processamentos" / "process1"
            process_dir.mkdir(parents=True)
            (process_dir / "municipio.csv").write_bytes(b"b" * 20)
            geocoding_dir = data / "geocodificacoes" / "geo1"
            geocoding_dir.mkdir(parents=True)
            (geocoding_dir / "mapa.geojson").write_bytes(b"c" * 30)
            processes = [{"job_id": "process1", "status": "completed", "competence": "2026-07",
                          "uf": "SP", "municipality_name": "MOGI", "rows_found": 1}]
            geocodings = [{"job_id": "geo1", "process_job_id": "process1", "status": "completed",
                           "competence": "2026-07", "municipality_name": "MOGI"}]
            projects = [{"project_id": "p1", "name": "Um", "competence": "2026-07",
                         "process_job_id": "process1", "geocoding_job_id": "geo1"},
                        {"project_id": "p2", "name": "Dois", "competence": "2026-07",
                         "process_job_id": "process1", "geocoding_job_id": "geo1"}]
            overview = library.storage_overview(processes, geocodings, projects, {"2026-07"})
            self.assertEqual(overview["summary"]["physical_size"], 60)
            self.assertEqual(overview["summary"]["shared_size"], 60)
            self.assertEqual(overview["projects"][0]["logical_size"], 60)
            self.assertEqual(overview["projects"][0]["shared_size"], 60)


if __name__ == "__main__": unittest.main()
