import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

import pandas as pd

from backend.processor import ESTABLISHMENT_COLUMNS, MunicipalProcessor, ReferenceLibrary, build_cnpj, clean_alphanumeric
from backend.cnae_hierarchy import load_cnae_hierarchy
from backend.storage import StorageLibrary
from backend.geocoder import GeocodingBridge


def make_zip(path: Path, member: str, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, content.encode("latin1"))


def make_uf_reference(root: Path, code: str, uf: str) -> Path:
    path = root / "referencias" / "MunicipiosUF.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"CODIGO;IBGE;NOME;NOME_IBGE;UF\n{code};0000000;TESTE;Teste;{uf}\n", encoding="latin1")
    return path


class ProcessorTests(unittest.TestCase):
    def test_partial_month_requires_acceptance_and_records_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            references = {}
            for name, member, content in [
                ("Cnaes.zip", "CNAE.CSV", '"6201501";"ATIVIDADE"\n'),
                ("Municipios.zip", "MUNICIPIOS.CSV", '"6713";"MOGI DAS CRUZES"\n'),
                ("Motivos.zip", "MOTIVOS.CSV", '"00";"SEM MOTIVO"\n'),
                ("Paises.zip", "PAISES.CSV", '"105";"BRASIL"\n'),
            ]:
                path = data / "referencias" / name
                make_zip(path, member, content)
                references[name] = {"path": str(path)}
            references["MunicipiosUF.csv"] = {"path": str(make_uf_reference(data, "6713", "SP"))}
            (data / "referencias" / "atual.json").write_text(json.dumps({"references": references}), encoding="utf-8")
            values = {column: "" for column in ESTABLISHMENT_COLUMNS}
            values.update(cnpj_basico="12345678", cnpj_ordem="0001", cnpj_dv="99", uf="SP",
                          municipio_codigo_receita="6713", situacao_cadastral="02")
            row = ";".join(f'"{values[column]}"' for column in ESTABLISHMENT_COLUMNS) + "\n"
            folder = data / "competencias" / "2026-11"
            official = []
            for index in range(10):
                name = f"Estabelecimentos{index}.zip"
                if index < 2: make_zip(folder / name, "DADOS.ESTABELE", row)
                official.append({"name": name, "kind": "establishment",
                                 "size": (folder / name).stat().st_size if index < 2 else 100})

            class FakeCatalog:
                def files(self, competence): return official

            library = StorageLibrary(data)
            library.register("2026-11", folder, "teste", True)
            manager = MunicipalProcessor(data, FakeCatalog(), library)
            with self.assertRaisesRegex(ValueError, "Confirme"):
                manager.create("2026-11", "SP", "6713", "MOGI DAS CRUZES")
            job = manager.create("2026-11", "SP", "6713", "MOGI DAS CRUZES", accept_incomplete=True)
            for _ in range(100):
                state = manager.get(job["job_id"])
                if state["status"] not in {"queued", "running"}: break
                time.sleep(.05)
            self.assertEqual(state["status"], "completed", state.get("logs"))
            self.assertTrue(state["is_partial"])
            self.assertEqual(state["source_files"], ["Estabelecimentos0.zip", "Estabelecimentos1.zip"])
            self.assertEqual(len(state["missing_source_files"]), 8)
            self.assertEqual(state["official_file_count"], 10)
            self.assertTrue(state["incomplete_acknowledged_at"])
            summary = pd.read_csv(data / "processamentos" / job["job_id"] / "resumo_processamento.csv", sep=";")
            self.assertTrue(summary.loc[0, "cobertura_parcial"])
            self.assertEqual(summary.loc[0, "partes_usadas"], 2)
            output = pd.read_csv(manager.output_path(job["job_id"]), sep=";", dtype=str, encoding="utf-8-sig")
            self.assertEqual(set(output["cobertura_parcial"]), {"True"})
            self.assertEqual(set(output["partes_usadas"]), {"2"})

    def test_municipality_search_uses_cache_and_refreshes_when_reference_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "referencias" / "Municipios.zip"
            make_zip(reference, "MUNICIPIOS.CSV", '"4177";"BRASOPOLIS"\n')
            pointer = root / "referencias" / "atual.json"
            uf_path = make_uf_reference(root, "4177", "MG")
            pointer.write_text(json.dumps({"references": {"Municipios.zip": {"path": str(reference)},
                                                          "MunicipiosUF.csv": {"path": str(uf_path)}}}), encoding="utf-8")
            library = ReferenceLibrary(root)
            self.assertEqual(library.municipalities("brasopolis"), [{"code": "4177", "name": "BRASOPOLIS", "uf": "MG"}])
            self.assertEqual(library.municipalities("braso", "MG"), [{"code": "4177", "name": "BRASOPOLIS", "uf": "MG"}])
            self.assertEqual(library.municipalities("braso", "SP"), [])
            self.assertEqual(library._municipality_index.cache_info().hits, 2)
            make_zip(reference, "MUNICIPIOS.CSV", '"4177";"BRASOPOLIS"\n"1234";"ÁGUAS CLARAS"\n')
            self.assertEqual(library.municipalities("aguas"), [{"code": "1234", "name": "ÁGUAS CLARAS", "uf": library._municipality_ufs().get("1234")}])

    def test_cnae_23_hierarchy_is_loaded(self):
        path = Path(__file__).parent.parent / "CNAE_Subclasses_2_3_Estrutura_Detalhada.xlsx"
        if not path.exists(): self.skipTest("Planilha CNAE opcional não distribuída nesta cópia")
        hierarchy = load_cnae_hierarchy(path)
        self.assertGreater(len(hierarchy), 1300)
        self.assertEqual(hierarchy["6201501"]["cnae_secao_codigo"], "J")
        self.assertEqual(hierarchy["6201501"]["cnae_divisao_codigo"], "62")
        self.assertEqual(hierarchy["6201501"]["cnae_grupo_codigo"], "620")

    def test_alphanumeric_cnpj_is_preserved(self):
        frame = pd.DataFrame([{"cnpj_basico": "12.ABC.345", "cnpj_ordem": "Z001", "cnpj_dv": "9X"}])
        self.assertEqual(clean_alphanumeric("12.ABC/345"), "12ABC345")
        self.assertEqual(build_cnpj(frame).iloc[0], "12ABC345Z0019X")

    def test_finish_merges_multiple_parts_in_csv_and_parquet(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            manager = MunicipalProcessor(data, None, StorageLibrary(data))
            for output_format in ("csv", "parquet"):
                job_dir = data / output_format
                partials = job_dir / "partials"
                partials.mkdir(parents=True)
                pd.DataFrame({"cnpj_completo": ["0001", "0002"], "nome_fantasia": ["A", "B"]}).to_csv(
                    partials / "partial_00.csv", sep=";", index=False, encoding="utf-8-sig")
                pd.DataFrame({"cnpj_completo": ["0003"], "nome_fantasia": ["C"]}).to_csv(
                    partials / "partial_01.csv", sep=";", index=False, encoding="utf-8-sig")
                job = {"competence": "2026-07", "uf": "SP", "municipality_code": "6713",
                       "municipality_name": "MOGI", "job_id": output_format, "output_format": output_format,
                       "source_files": ["0.zip", "1.zip"], "official_file_count": 10,
                       "is_partial": True, "rows_read": 30, "active_only": True}
                output = manager._finish(job_dir, job)
                result = (pd.read_csv(output, sep=";", dtype=str, encoding="utf-8-sig")
                          if output_format == "csv" else pd.read_parquet(output).astype(str))
                self.assertEqual(result["cnpj_completo"].tolist(), ["0001", "0002", "0003"])
                self.assertEqual(result["partes_usadas"].tolist(), ["2", "2", "2"])
                self.assertEqual(result["cobertura_parcial"].tolist(), ["True", "True", "True"])
                summary = pd.read_csv(job_dir / "resumo_processamento.csv", sep=";")
                self.assertEqual(int(summary.iloc[0]["linhas_resultado"]), 3)

    def test_complete_synthetic_pipeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            refs = data / "referencias" / "versoes"
            definitions = {
                "Cnaes.zip": ("CNAE.CSV", '"6201501";"DESENVOLVIMENTO DE PROGRAMAS"\n'),
                "Municipios.zip": ("MUNICIPIOS.CSV", '"6713";"MOGI DAS CRUZES"\n'),
                "Motivos.zip": ("MOTIVOS.CSV", '"00";"SEM MOTIVO"\n'),
                "Paises.zip": ("PAISES.CSV", '"105";"BRASIL"\n'),
            }
            current = {"references": {}}
            for index, (name, (member, content)) in enumerate(definitions.items()):
                path = refs / str(index) / name
                make_zip(path, member, content)
                current["references"][name] = {"path": str(path), "sha256": str(index)}
            (data / "referencias").mkdir(exist_ok=True)
            current["references"]["MunicipiosUF.csv"] = {"path": str(make_uf_reference(data, "6713", "SP"))}
            hierarchy_source = Path(__file__).parent.parent / "CNAE_Subclasses_2_3_Estrutura_Detalhada.xlsx"
            if hierarchy_source.is_file():
                hierarchy_target = refs / "cnae" / hierarchy_source.name
                hierarchy_target.parent.mkdir(parents=True, exist_ok=True)
                hierarchy_target.write_bytes(hierarchy_source.read_bytes())
                current["references"][hierarchy_source.name] = {"path": str(hierarchy_target)}
            (data / "referencias" / "atual.json").write_text(json.dumps(current), encoding="utf-8")

            values = {column: "" for column in ESTABLISHMENT_COLUMNS}
            values.update({"cnpj_basico": "12ABC345", "cnpj_ordem": "Z001", "cnpj_dv": "9X",
                           "nome_fantasia": "EMPRESA TESTE", "situacao_cadastral": "02",
                           "motivo_situacao_cadastral": "00", "pais": "105", "data_inicio_atividade": "20260101",
                           "cnae_fiscal_principal": "6201501", "tipo_logradouro": "RUA", "logradouro": "TESTE",
                           "numero": "10", "bairro": "CENTRO", "cep": "08700000", "uf": "SP",
                           "municipio_codigo_receita": "6713"})
            row = ";".join(f'"{values[column]}"' for column in ESTABLISHMENT_COLUMNS) + "\n"
            official = []
            for index in range(12):
                path = data / "competencias" / "2026-07" / f"Estabelecimentos{index}.zip"
                make_zip(path, "DADOS.ESTABELE", row)
                official.append({"name": path.name, "kind": "establishment", "size": path.stat().st_size, "etag": str(index)})

            class FakeCatalog:
                def files(self, competence): return official

            library = StorageLibrary(data)
            library.register("2026-07", data / "competencias" / "2026-07", "teste", True)
            manager = MunicipalProcessor(data, FakeCatalog(), library)
            self.assertEqual(manager.references.municipalities("MOGI")[0]["code"], "6713")
            validation = manager.start_validation("2026-07")
            for _ in range(100):
                validation_state = manager.get_validation(validation["validation_id"])
                if validation_state["status"] not in {"queued", "running"}: break
                time.sleep(.03)
            self.assertEqual(validation_state["status"], "completed", validation_state)
            manifest = manager._load_manifest("2026-07")
            self.assertEqual(len(manifest["files"]), 12)
            job = manager.create("2026-07", "SP", "6713", "MOGI DAS CRUZES", True, "csv")
            for _ in range(100):
                state = manager.get(job["job_id"])
                if state["status"] not in {"queued", "running", "cancelling"}: break
                time.sleep(.05)
            self.assertEqual(state["status"], "completed", state.get("logs"))
            self.assertEqual(state["rows_found"], 12)
            self.assertEqual(state["total_files"], 12)
            self.assertGreater(state["processing_seconds"], 0)
            result = pd.read_csv(manager.output_path(job["job_id"]), sep=";", dtype=str, encoding="utf-8-sig")
            self.assertEqual(result.iloc[0]["cnpj_completo"], "12ABC345Z0019X")
            self.assertEqual(result.iloc[0]["cnae_principal_desc"], "DESENVOLVIMENTO DE PROGRAMAS")
            if (Path(__file__).parent.parent / "CNAE_Subclasses_2_3_Estrutura_Detalhada.xlsx").exists():
                self.assertEqual(result.iloc[0]["cnae_secao_codigo"], "J")
                self.assertEqual(result.iloc[0]["cnae_divisao_codigo"], "62")
                self.assertEqual(result.iloc[0]["cnae_grupo_codigo"], "620")
            else:
                self.assertTrue(pd.isna(result.iloc[0]["cnae_secao_codigo"]))
            bridge = GeocodingBridge(data, manager, "http://127.0.0.1:1")
            self.assertEqual(len(bridge.artifacts()), 1)
            self.assertFalse(bridge.health()["online"])


if __name__ == "__main__": unittest.main()
