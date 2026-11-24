"""Isolated Python geocodebr worker for the GeoCNPJ job pipeline."""

from pathlib import Path
import sys

import pandas as pd
import polars as pl
from geocodebr import definir_campos, definir_pasta_cache, geocode


def main() -> None:
    if len(sys.argv) != 6:
        raise SystemExit("Uso: run_geocodebr.py entrada.csv saida.csv cache_dir n_cores resolver_empates")

    input_csv, output_csv, cache_dir, n_cores, resolver_empates = sys.argv[1:]
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    definir_pasta_cache(cache_dir, verboso=False)

    # The GeoCNPJ CSV uses semicolons and UTF-8 BOM; retain CEP and address IDs as text.
    frame = pd.read_csv(input_csv, sep=";", dtype=str, encoding="utf-8-sig").fillna("")
    enderecos = pl.from_pandas(frame)
    campos = definir_campos(
        logradouro="logradouro_geocode",
        numero="numero_geocode",
        cep="cep_geocode",
        localidade="bairro_geocode",
        municipio="municipio_geocode",
        estado="uf_geocode",
    )
    result = geocode(
        enderecos=enderecos,
        campos_endereco=campos,
        resultado_completo=True,
        resolver_empates=resolver_empates.lower() == "true",
        h3_res=None,
        resultado_gpd=False,
        verboso=False,
        cache=True,
        n_cores=max(int(n_cores), 1),
    )
    result.to_pandas().to_csv(output_csv, sep=";", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
