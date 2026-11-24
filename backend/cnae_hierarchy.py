from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

MAIN_SHEET = "Estrutura Det. CNAE Subclass2.3"
SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _rows(path: Path):
    """Lê as células necessárias do XLSX usando apenas a biblioteca padrão."""
    ns = {"m": SPREADSHEET_NS, "r": REL_NS}
    with zipfile.ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in item.iter(f"{{{SPREADSHEET_NS}}}t")) for item in root]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
        sheet = next((item for item in workbook.find("m:sheets", ns) if item.attrib["name"] == MAIN_SHEET), None)
        if sheet is None:
            raise ValueError(f"Aba ausente na referência CNAE: {MAIN_SHEET}")
        target = targets[sheet.attrib[f"{{{REL_NS}}}id"]].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        worksheet = ET.fromstring(archive.read(target))
        for row in worksheet.findall(".//m:sheetData/m:row", ns):
            values = {}
            for cell in row.findall("m:c", ns):
                column = re.match(r"[A-Z]+", cell.attrib.get("r", ""))
                if not column:
                    continue
                value_node = cell.find("m:v", ns)
                value = "" if value_node is None else value_node.text or ""
                if cell.attrib.get("t") == "s" and value:
                    value = shared[int(value)]
                elif cell.attrib.get("t") == "inlineStr":
                    value = "".join(node.text or "" for node in cell.iter(f"{{{SPREADSHEET_NS}}}t"))
                values[column.group()] = value.strip()
            yield values


def load_cnae_hierarchy(path: Path) -> dict[str, dict[str, str]]:
    """Relaciona cada subclasse CNAE aos níveis seção, divisão e grupo."""
    current = {"secao": ("", ""), "divisao": ("", ""), "grupo": ("", "")}
    hierarchy = {}
    for row in _rows(path):
        description = row.get("F", "")
        if row.get("A") and len(row["A"]) == 1:
            current["secao"] = (row["A"], description)
        elif row.get("B"):
            current["divisao"] = (_digits(row["B"]).zfill(2), description)
        elif row.get("C"):
            current["grupo"] = (_digits(row["C"]).zfill(3), description)
        elif row.get("E"):
            code = _digits(row["E"]).zfill(7)
            hierarchy[code] = {
                "cnae_secao_codigo": current["secao"][0], "cnae_secao_descricao": current["secao"][1],
                "cnae_divisao_codigo": current["divisao"][0], "cnae_divisao_descricao": current["divisao"][1],
                "cnae_grupo_codigo": current["grupo"][0], "cnae_grupo_descricao": current["grupo"][1],
            }
    if not hierarchy:
        raise ValueError("A referência CNAE não contém subclasses reconhecíveis.")
    return hierarchy
