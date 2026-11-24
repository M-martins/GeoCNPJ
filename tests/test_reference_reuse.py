import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile

from backend.downloader import DownloadManager
from backend.storage import StorageLibrary


class ReferenceReuseTests(unittest.TestCase):
    def test_identical_catalog_version_reuses_local_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            manager = DownloadManager(data, None, StorageLibrary(data))
            first = manager.references_dir / "entrada" / "2026-10" / "Cnaes.zip"
            first.parent.mkdir(parents=True)
            with zipfile.ZipFile(first, "w") as archive:
                archive.writestr("Cnaes.csv", "1234567;Atividade\n")
            item = {"name": "Cnaes.zip", "kind": "reference", "size": first.stat().st_size,
                    "etag": "same-version"}
            manager._version_reference({"competence": "2026-10"}, item, first)
            self.assertEqual(manager.local_state("2026-11", item)["status"], "reusable")
            next_item = {**item, "status": "pending", "downloaded": 0}
            job = {"competence": "2026-11", "logs": []}
            with patch("backend.downloader.requests.get", side_effect=AssertionError("rede não deve ser usada")):
                manager._download_one(job, next_item, None)
            second = manager.references_dir / "entrada" / "2026-11" / "Cnaes.zip"
            self.assertEqual(second.read_bytes(), first.read_bytes())
            self.assertEqual(next_item["status"], "reused")
            self.assertEqual(manager._current_reference("Cnaes.zip")["source_competence"], "2026-11")


if __name__ == "__main__":
    unittest.main()
