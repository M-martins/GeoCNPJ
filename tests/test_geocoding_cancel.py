import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.geocoder import GeocodingBridge
from geo_engine import main as engine


class GeocodingCancellationTests(unittest.TestCase):
    def test_cancel_before_worker_starts_preserves_cancelled_state(self):
        with tempfile.TemporaryDirectory() as temp:
            job_id = "a1b2c3d4"
            job_dir = Path(temp) / job_id
            job_dir.mkdir()
            engine.save_status(job_dir, {"job_id": job_id, "status": "queued", "logs": []})
            with patch.object(engine, "JOBS_DIR", Path(temp)), patch.object(engine, "CANCEL_EVENTS", {job_id: threading.Event()}), patch.object(engine, "RUNNING_CHILDREN", {}):
                requested = engine.cancel_job(job_id)
                self.assertEqual(requested["status"], "cancelling")
                engine.run_job(job_id)
                result = engine.load_status(job_dir)
                self.assertEqual(result["status"], "cancelled")
                self.assertFalse((job_dir / "python_stdout.txt").exists())

    def test_bridge_forwards_stop_to_running_engine(self):
        with tempfile.TemporaryDirectory() as temp:
            bridge = GeocodingBridge(Path(temp), None, "http://127.0.0.1:8092/geo")
            bridge._save({"job_id": "job123", "status": "running", "remote_job_id": "a1b2c3d4", "can_cancel": True})
            response = Mock()
            response.json.return_value = {"status": "cancelling"}
            with patch("backend.geocoder.requests.post", return_value=response) as post:
                state = bridge.cancel("job123")
            post.assert_called_once_with("http://127.0.0.1:8092/geo/jobs/a1b2c3d4/cancel", timeout=25)
            self.assertEqual(state["status"], "cancelling")
            self.assertFalse(bridge.get("job123")["can_cancel"])
