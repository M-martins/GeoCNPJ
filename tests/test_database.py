import json
import tempfile
import unittest
from datetime import datetime, timedelta
from contextlib import closing
from pathlib import Path

from backend.database import OperationalStore


class OperationalStoreTests(unittest.TestCase):
    def test_migrates_json_with_backup_and_uses_sqlite(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "data"
            control = data / "controle"
            control.mkdir(parents=True)
            projects = control / "projetos.json"
            projects.write_text(json.dumps({"version": 1, "projects": [], "ignored_keys": []}), encoding="utf-8")
            jobs = control / "jobs_download"; jobs.mkdir()
            job = {"job_id": "d1", "status": "completed", "percent": 100, "created_at": "2026-01-01T00:00:00-03:00"}
            (jobs / "d1.json").write_text(json.dumps(job), encoding="utf-8")
            store = OperationalStore(data)
            result = store.migrate_json_controls()
            self.assertEqual(result["operations"], 1)
            self.assertTrue((control / "projetos.json.pre-sqlite.bak").exists())
            self.assertEqual(store.get_operation("download", "d1")["status"], "completed")
            self.assertTrue(store.path.exists())

    def test_active_operation_is_marked_interrupted_on_graceful_shutdown(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = OperationalStore(Path(temporary) / "data")
            state = {"job_id": "p1", "status": "running", "percent": 42,
                     "created_at": "2026-01-01T00:00:00-03:00"}
            store.put_operation("process", "p1", state)
            changed = store.interrupt_owned()
            self.assertEqual(changed[0]["operation_id"], "p1")
            recovered = store.get_operation("process", "p1")
            self.assertEqual(recovered["status"], "interrupted")
            self.assertEqual(store.recoverable()[0]["operation_id"], "p1")

    def test_lease_blocks_a_second_executor_and_expired_job_is_recovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "data"
            first = OperationalStore(data, executor_id="instance-a", lease_seconds=45)
            second = OperationalStore(data, executor_id="instance-b", lease_seconds=45)
            state = {"job_id": "d1", "status": "running", "percent": 10,
                     "created_at": "2026-01-01T00:00:00-03:00"}
            first.put_operation("download", "d1", state)
            with self.assertRaisesRegex(RuntimeError, "outra instância"):
                second.put_operation("download", "d1", {**state, "percent": 11})
            first.renew_owned_leases()
            self.assertEqual(first.owned_active()[0]["operation_id"], "d1")
            expired = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat(timespec="seconds")
            with closing(first._connect()) as db, db:
                db.execute("UPDATE operations SET lease_until=? WHERE operation_id='d1'", (expired,))
            changed = second.mark_abandoned()
            self.assertEqual(changed[0]["operation_id"], "d1")
            self.assertEqual(second.get_operation("download", "d1")["status"], "interrupted")

    def test_scans_registers_and_ignores_orphan_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "data"
            orphan = data / "processamentos" / "orphan1"
            orphan.mkdir(parents=True)
            status = {"job_id": "orphan1", "status": "completed", "percent": 100,
                      "created_at": "2026-01-01T00:00:00-03:00"}
            (orphan / "status.json").write_text(json.dumps(status), encoding="utf-8")
            store = OperationalStore(data)
            scan = store.scan_orphans([])
            item = next(row for row in scan["items"] if row["issue"] == "unregistered")
            store.handle_orphan(item["orphan_id"], "register", [])
            self.assertEqual(store.get_operation("process", "orphan1")["status"], "completed")
            unlinked = next(row for row in store.scan_orphans([])["items"] if row["issue"] == "unlinked")
            store.handle_orphan(unlinked["orphan_id"], "ignore", [])
            self.assertFalse(any(row["orphan_id"] == unlinked["orphan_id"] for row in store.scan_orphans([])["items"]))


if __name__ == "__main__": unittest.main()
