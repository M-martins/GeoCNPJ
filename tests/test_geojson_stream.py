import json
import tempfile
import unittest
from pathlib import Path

from backend.geojson_stream import stream_geojson


class GeojsonStreamTests(unittest.TestCase):
    def test_large_file_yields_all_features_and_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "large.geojson"
            feature = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-46, -23]},
                       "properties": {"name": "A" * 3000}}
            with path.open("w", encoding="utf-8") as output:
                output.write('{"type":"FeatureCollection","metadata":{"mapped":1500},"features":[')
                for i in range(1500):
                    if i: output.write(",")
                    output.write(json.dumps(feature))
                output.write("]}")
            self.assertGreater(path.stat().st_size, 4 * 1024 * 1024)
            items = stream_geojson(path)
            self.assertEqual(next(items), ("metadata", {"mapped": 1500}))
            self.assertEqual(sum(kind == "feature" for kind, _ in items), 1500)


if __name__ == "__main__": unittest.main()
