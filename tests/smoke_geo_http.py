"""Exercise the GeoCNPJ bridge, embedded Python GEO, ZIP and map with a prepared CSV."""

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.geocoder import GeocodingBridge
from backend.map_index import MapIndex


class SampleProcessor:
    def __init__(self, path: Path):
        self.path = path

    def output_path(self, job_id):
        assert job_id == "smoke"
        return self.path

    def get(self, job_id):
        assert job_id == "smoke"
        return {"competence": "teste", "municipality_name": "ARUJA"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prepared_csv", type=Path)
    parser.add_argument("--rows", type=int, default=5)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="geocnpj_smoke_") as temp:
        root = Path(temp)
        sample = root / "amostra.csv"
        pd.read_csv(args.prepared_csv, sep=";", dtype=str, encoding="utf-8-sig").head(args.rows).to_csv(
            sample, sep=";", index=False, encoding="utf-8-sig"
        )
        bridge = GeocodingBridge(root, SampleProcessor(sample), "http://127.0.0.1:8092/geo")
        job = bridge.create("smoke")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = bridge.get(job["job_id"])
            if state["status"] in {"completed", "error"}:
                break
            time.sleep(1)
        else:
            raise TimeoutError(job["job_id"])
        if state["status"] != "completed":
            raise RuntimeError(state["message"])
        package = bridge.download_path(job["job_id"])
        map_file = bridge.map_path(job["job_id"])
        summary = MapIndex(bridge).summary(job["job_id"])
        assert package.stat().st_size > 0
        assert summary["metadata"]["total_records"] == args.rows
        print(json.dumps({
            "status": state["status"],
            "rows": args.rows,
            "mapped": summary["metadata"]["mapped"],
            "package_bytes": package.stat().st_size,
            "map_bytes": map_file.stat().st_size,
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
