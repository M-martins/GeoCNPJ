"""Compare GeoJSON parsing memory; synthetic data only, no official downloads."""
import argparse
import gc
import json
import tempfile
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.geojson_stream import stream_geojson


def measure(fn):
    gc.collect()
    tracemalloc.start()
    started = time.perf_counter()
    count = fn()
    seconds = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return count, seconds, peak / 1024**2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=20_000)
    args = parser.parse_args()
    if not 1 <= args.records <= 200_000:
        parser.error("--records deve estar entre 1 e 200000")
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "benchmark.geojson"
        with source.open("w", encoding="utf-8") as output:
            output.write('{"type":"FeatureCollection","metadata":{"mapped":'+str(args.records)+'},"features":[')
            for i in range(args.records):
                if i: output.write(",")
                output.write(json.dumps({"type": "Feature", "geometry": {"type": "Point", "coordinates": [-46.2, -23.5]},
                                         "properties": {"cnpj_completo": f"{i:014d}", "nome_fantasia": "Empresa de exemplo",
                                                        "logradouro": "Rua Quinze de Novembro", "numero": str(i % 1000),
                                                        "bairro": "Centro", "cnae_principal_desc": "Comercio varejista"}},
                                        ensure_ascii=False))
            output.write("]}")
        old = measure(lambda: len(json.loads(source.read_text(encoding="utf-8"))["features"]))
        new = measure(lambda: sum(kind == "feature" for kind, _ in stream_geojson(source)))
        assert old[0] == new[0] == args.records
        print(f"Arquivo: {source.stat().st_size / 1024**2:.1f} MiB; registros: {args.records}")
        print(f"Leitura integral: {old[1]:.3f} s; pico Python {old[2]:.1f} MiB")
        print(f"Leitura em fluxo: {new[1]:.3f} s; pico Python {new[2]:.1f} MiB")
        print("Mede apenas a leitura JSON sintética; não inclui geração de pontos nem SQLite.")


if __name__ == "__main__":
    main()
