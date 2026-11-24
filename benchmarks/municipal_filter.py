"""Mede leitura e filtro de um bloco real de Estabelecimentos da Receita.

Uso, na raiz do projeto: python -m benchmarks.municipal_filter CAMINHO_DO_ZIP SP 6231
"""

import argparse
import json
import time
import zipfile

import pandas as pd

from backend.processor import ESTABLISHMENT_COLUMNS, clean_digits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("zip_path")
    parser.add_argument("uf")
    parser.add_argument("municipality_code")
    parser.add_argument("--rows", type=int, default=100_000)
    args = parser.parse_args()

    started = time.perf_counter()
    with zipfile.ZipFile(args.zip_path) as archive:
        member = next(item for item in archive.infolist() if not item.is_dir())
        with archive.open(member) as source:
            chunk = next(pd.read_csv(source, sep=";", header=None, names=ESTABLISHMENT_COLUMNS,
                                     dtype=str, encoding="latin1", chunksize=args.rows,
                                     low_memory=False, quotechar='"'))
    read_seconds = time.perf_counter() - started

    started = time.perf_counter()
    old = chunk["uf"].fillna("").str.upper().str.strip().eq(args.uf)
    old &= chunk["municipio_codigo_receita"].map(clean_digits).str.zfill(4).eq(args.municipality_code)
    old &= chunk["situacao_cadastral"].map(clean_digits).str.zfill(2).eq("02")
    old_seconds = time.perf_counter() - started

    started = time.perf_counter()
    new = chunk["uf"].eq(args.uf)
    new &= chunk["municipio_codigo_receita"].eq(args.municipality_code)
    new &= chunk["situacao_cadastral"].eq("02")
    new_seconds = time.perf_counter() - started

    if not old.equals(new):
        raise SystemExit("Os filtros produziram resultados diferentes; não use a otimização nesta base.")
    print(json.dumps({"rows": len(chunk), "matches": int(new.sum()),
                      "read_seconds": round(read_seconds, 3),
                      "old_filter_seconds": round(old_seconds, 3),
                      "new_filter_seconds": round(new_seconds, 3),
                      "filter_speedup": round(old_seconds / new_seconds, 1),
                      "chunk_speedup": round((read_seconds + old_seconds) / (read_seconds + new_seconds), 2)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
