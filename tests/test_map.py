import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from geo_engine.main import criar_geojson

from backend.geocoder import classify_quality, prepare_map_geojson


class MapTests(unittest.TestCase):
    def test_quality_uses_pipeline_decision(self):
        self.assertEqual(classify_quality({"decisao_geocode": "aceito_automaticamente"}), "high")
        self.assertEqual(classify_quality({"decisao_geocode": "aceito_com_alerta"}), "alert")
        self.assertEqual(classify_quality({"decisao_geocode": "revisar_empate"}), "review")
        self.assertEqual(classify_quality({}), "unknown")

    def test_full_geojson_stream_preserves_fields_and_skips_invalid_coordinates(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "full.geojson"
            frame = pd.DataFrame({"cnpj_completo": ["0001", "0002", "0003"],
                                  "nome_fantasia": ["Loja", "Sem ponto", "Fora"],
                                  "latitude": ["-23,5", "", "91"],
                                  "longitude": ["-46,2", "", "-46"]})
            self.assertEqual(criar_geojson(frame, path), 1)
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result["metadata"]["total_sem_coordenada"], 2)
            self.assertEqual(result["features"][0]["properties"]["cnpj_completo"], "0001")
            self.assertEqual(result["features"][0]["geometry"]["coordinates"], [-46.2, -23.5])
            self.assertEqual(len(result["features"]), 1)

    def test_lightweight_map_and_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / "source.geojson"; target = root / "map.geojson"
            decisions = ["aceito_automaticamente", "aceito_com_alerta", "revisar_baixa_precisao", ""]
            features = []
            for index, decision in enumerate(decisions):
                features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [-46.1+index/100, -23.5]},
                                 "properties": {"cnpj_completo": str(index), "decisao_geocode": decision,
                                                "score_geocode": 90-index*20, "logradouro": "RUA TESTE", "numero": "10",
                                                "bairro": "Centro", "campo_pesado": "não copiar"}})
            source.write_text(json.dumps({"type": "FeatureCollection", "metadata": {"total_registros_csv": 6, "total_sem_coordenada": 2}, "features": features}), encoding="utf-8")
            summary = prepare_map_geojson(source, target); result = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(summary["mapped"], 4)
            self.assertEqual(summary["without_coordinates"], 2)
            self.assertEqual(summary["quality"], {"high": 1, "alert": 1, "review": 1, "unknown": 1})
            self.assertNotIn("campo_pesado", result["features"][0]["properties"])
            self.assertEqual(result["features"][0]["properties"]["bairro"], "Centro")
            self.assertEqual(result["features"][0]["properties"]["logradouro"], "RUA TESTE")
            self.assertEqual(result["features"][0]["properties"]["numero"], "10")


if __name__ == "__main__": unittest.main()
