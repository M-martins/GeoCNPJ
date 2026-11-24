"""Atualiza artefatos existentes com seção, divisão e grupo da CNAE 2.3."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.cnae_hierarchy import load_cnae_hierarchy  # noqa: E402

FIELDS = ("cnae_secao_codigo", "cnae_secao_descricao", "cnae_divisao_codigo",
          "cnae_divisao_descricao", "cnae_grupo_codigo", "cnae_grupo_descricao")


def enrich_properties(properties, hierarchy):
    item = hierarchy.get(str(properties.get("cnae_fiscal_principal", "")).zfill(7), {})
    for field in FIELDS:
        properties[field] = item.get(field, "")


def update_geojson(path: Path, hierarchy):
    data = json.loads(path.read_text(encoding="utf-8"))
    for feature in data.get("features", []):
        enrich_properties(feature.setdefault("properties", {}), hierarchy)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)
    return len(data.get("features", []))


def update_csv(path: Path, hierarchy):
    frame = pd.read_csv(path, sep=";", dtype=str, encoding="utf-8-sig").fillna("")
    codes = frame["cnae_fiscal_principal"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(7)
    for field in FIELDS:
        frame[field] = codes.map(lambda code: hierarchy.get(code, {}).get(field, ""))
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, sep=";", index=False, encoding="utf-8-sig")
    temporary.replace(path)
    return len(frame)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True, help="Identificador da geocodificação")
    args = parser.parse_args()
    hierarchy = load_cnae_hierarchy(ROOT / "CNAE_Subclasses_2_3_Estrutura_Detalhada.xlsx")
    status_path = ROOT / "data" / "geocodificacoes" / args.job / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    process_id = status["process_job_id"]
    geojson = status_path.parent / "resultado_completo.geojson"
    csv_files = list((ROOT / "data" / "processamentos" / process_id).glob("cnpj_*.csv"))
    print(f"GeoJSON: {update_geojson(geojson, hierarchy)} registros")
    for path in csv_files:
        print(f"CSV: {update_csv(path, hierarchy)} registros")


if __name__ == "__main__":
    main()
