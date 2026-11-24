import asyncio
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from backend.api.geocoding import map_export, query_filters, safe_csv_cell
from backend.application import UploadBodyLimit
from geo_engine.main import save_upload


class SecurityTests(unittest.TestCase):
    def test_upload_limit_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "input.csv"
            with self.assertRaises(ValueError):
                save_upload(io.BytesIO(b"123456789"), target, max_bytes=8)
            self.assertFalse(target.exists())
            self.assertEqual(save_upload(io.BytesIO(b"12345678"), target, max_bytes=8), 8)
            self.assertEqual(target.read_bytes(), b"12345678")

    def test_upload_body_is_rejected_before_parser(self):
        reached = []
        async def downstream(scope, receive, send):
            while True:
                message = await receive()
                reached.append(message.get("body", b""))
                if not message.get("more_body"):
                    break
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        async def run():
            parts = iter([{"type": "http.request", "body": b"1234", "more_body": True},
                          {"type": "http.request", "body": b"5678", "more_body": False}])
            sent = []
            async def receive(): return next(parts)
            async def send(message): sent.append(message)
            scope = {"type": "http", "path": "/geo/jobs", "method": "POST"}
            await UploadBodyLimit(downstream, max_bytes=6)(scope, receive, send)
            return sent
        sent = asyncio.run(run())
        self.assertEqual(sent[0]["status"], 413)
        self.assertEqual(reached, [b"1234"])

    def test_upload_stream_returns_413_through_fastapi_middleware(self):
        app = FastAPI()
        @app.middleware("http")
        async def passthrough(request: Request, call_next):
            return await call_next(request)
        @app.post("/geo/jobs")
        async def endpoint(request: Request):
            return {"size": len(await request.body())}
        app.add_middleware(UploadBodyLimit, max_bytes=5)
        def chunks():
            yield b"1234"
            yield b"5678"
        with TestClient(app) as client:
            response = client.post("/geo/jobs", content=chunks())
        self.assertEqual(response.status_code, 413)

    def test_map_filter_limits(self):
        with self.assertRaises(HTTPException) as error:
            query_filters(name="x" * 161)
        self.assertEqual(error.exception.status_code, 422)
        with self.assertRaises(HTTPException) as error:
            query_filters(selected=",".join(str(i) for i in range(501)))
        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(query_filters(selected="123,456")["selected"], "123,456")

    def test_csv_export_escapes_formulas_but_geojson_keeps_source(self):
        feature = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-46.2, -23.5]},
                   "properties": {"cnpj_completo": "123", "nome_fantasia": "=HYPERLINK(\"https://bad.example\")",
                                  "logradouro": "  +1+2", "numero": "-5"}}
        class Index:
            def iter_features(self, job_id, filters):
                yield {**feature, "properties": dict(feature["properties"])}
        services = SimpleNamespace(map_index=Index(), projects=SimpleNamespace(reviews=lambda project_id: {}))
        async def collect(response):
            return b"".join([chunk.encode() if isinstance(chunk, str) else chunk async for chunk in response.body_iterator]).decode("utf-8-sig")
        csv_text = asyncio.run(collect(map_export("job", s=services)))
        row = next(csv.DictReader(io.StringIO(csv_text), delimiter=";"))
        self.assertTrue(row["nome_fantasia"].startswith("'="))
        self.assertTrue(row["logradouro"].startswith("'  +"))
        self.assertTrue(row["numero"].startswith("'-"))
        geojson_text = asyncio.run(collect(map_export("job", format="geojson", s=services)))
        self.assertEqual(json.loads(geojson_text)["features"][0]["properties"]["nome_fantasia"], feature["properties"]["nome_fantasia"])
        self.assertEqual(safe_csv_cell(-5), -5)


if __name__ == "__main__": unittest.main()
