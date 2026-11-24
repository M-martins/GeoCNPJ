import json
import tempfile
import unittest
from pathlib import Path

from backend.map_index import MapIndex


class FakeGeocoder:
    def __init__(self, path): self.path = path
    def map_path(self, job_id): return self.path
    def full_map_path(self, job_id): return self.path


class MapIndexTests(unittest.TestCase):
    def test_indexes_more_than_one_write_batch(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "map.geojson"
            features = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [-46.2, -23.5]},
                         "properties": {"cnpj_completo": str(i), "nome_fantasia": "Empresa"}}
                        for i in range(1205)]
            path.write_text(json.dumps({"type": "FeatureCollection", "metadata": {"mapped": 1205},
                                        "features": features}), encoding="utf-8")
            index = MapIndex(FakeGeocoder(path))
            self.assertEqual(index.records("job", {})["total"], 1205)
            self.assertEqual(index.summary("job")["metadata"]["mapped"], 1205)

    def test_indexes_filters_pages_and_clusters(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "map.geojson"
            features = []
            for index in range(25):
                properties = {"cnpj_completo": str(index), "nome_fantasia": f"Empresa {index}",
                              "logradouro": "QUINZE DE NOVEMBRO" if index < 20 else "SETE DE NOVEMBRO",
                              "numero": str(index), "bairro": "CENTRO", "quality": "high",
                              "score_geocode": 100, "precisao": "numero", "decisao_geocode": "aceito",
                              "cnae_fiscal_principal": "6201501", "cnae_principal_desc": "Desenvolvimento de programas"}
                features.append({"type":"Feature","geometry":{"type":"Point","coordinates":[-46.2+index/10000,-23.5]},"properties":properties})
            path.write_text(json.dumps({"type":"FeatureCollection","metadata":{"total_records":25,"mapped":25,"without_coordinates":0,"quality":{"review":0}},"features":features}),encoding="utf-8")
            index = MapIndex(FakeGeocoder(path))
            summary = index.summary("job")
            self.assertEqual(summary["metadata"]["mapped"], 25)
            self.assertEqual(sum(summary["metadata"]["quality"].values()), 25)
            self.assertTrue(path.with_name("mapa_territorial_v2.sqlite3").exists())
            page = index.records("job", {"street":"QUINZE NOVEMBRO"}, page=2, page_size=7)
            self.assertEqual(page["total"], 20)
            self.assertEqual(len(page["features"]), 7)
            self.assertTrue(all("QUINZE" in f["properties"]["logradouro"] for f in page["features"]))
            clusters = index.viewport("job", (-47,-24,-45,-23), 10, {})
            self.assertTrue(clusters["features"][0]["properties"]["cluster"])
            points = index.viewport("job", (-47,-24,-45,-23), 17, {})
            self.assertEqual(len(points["features"]), 25)
            exported = next(index.iter_features("job", {"selected":"0"}))
            self.assertEqual(exported["properties"]["cnae_fiscal_principal"], "6201501")
            self.assertEqual(set(points["features"][0]["properties"]), {"cnpj_completo", "nome_fantasia", "quality"})
            activity = index.records("job", {"activity":"DESENVOLVIMENTO PROGRAMAS"}, 1, 10)
            self.assertEqual(activity["total"], 25)
            suggestion = index.suggestions("job", "activity", "DESENVOLVIMENTO")[0]
            self.assertEqual(suggestion["properties"]["cnae_fiscal_principal"], "6201501")
            detail = index.detail("job", "0")
            self.assertEqual(detail["properties"]["cnae_principal_desc"], "Desenvolvimento de programas")


if __name__ == "__main__": unittest.main()
