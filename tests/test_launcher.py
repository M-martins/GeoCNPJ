import io
import json
import unittest
from unittest.mock import patch

from scripts import launch


class LauncherTests(unittest.TestCase):
    def test_health_identifies_this_installation_without_release_number(self):
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()

        def result(project_root):
            payload = {"ok": True, "app": "GeoCNPJ", "project_root": str(project_root)}
            with patch.object(launch.urllib.request, "urlopen", return_value=Response(json.dumps(payload).encode())):
                return launch.health()

        self.assertEqual(result(launch.ROOT), (True, str(launch.ROOT)))
        self.assertEqual(result(launch.ROOT.parent / "outra-instalacao"),
                         (False, str(launch.ROOT.parent / "outra-instalacao")))


if __name__ == "__main__": unittest.main()
