from __future__ import annotations

import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree

import requests

COMPETENCE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
ESTABLISHMENT_RE = re.compile(r"^Estabelecimentos(\d+)\.zip$", re.I)
REFERENCE_NAMES = {"Cnaes.zip", "Municipios.zip", "Motivos.zip", "Paises.zip"}
MUNICIPALITY_UF_NAME = "MunicipiosUF.csv"
MUNICIPALITY_UF_URL = "https://www.gov.br/receitafederal/dados/municipios.csv/@@download/file"
CNAE_HIERARCHY_NAME = "CNAE_Subclasses_2_3_Estrutura_Detalhada.xlsx"
CNAE_HIERARCHY_URL = "https://cnae.ibge.gov.br/images/concla/documentacao/CNAE_Subclasses_2_3_Estrutura_Detalhada.xlsx"
EXTERNAL_REFERENCES = {MUNICIPALITY_UF_NAME: MUNICIPALITY_UF_URL, CNAE_HIERARCHY_NAME: CNAE_HIERARCHY_URL}


@dataclass(frozen=True)
class RemoteEntry:
    name: str
    path: str
    is_directory: bool
    size: int | None = None
    etag: str | None = None
    modified: str | None = None

    def as_dict(self) -> dict:
        kind = "establishment" if ESTABLISHMENT_RE.fullmatch(self.name) else "reference" if self.name in REFERENCE_NAMES else "other"
        return {"name": self.name, "path": self.path, "is_directory": self.is_directory,
                "size": self.size, "etag": self.etag, "modified": self.modified, "kind": kind}


class ReceitaCatalog:
    def __init__(self, base_url: str, share_token: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/") + "/"
        self.share_token = share_token
        self.timeout = timeout

    @property
    def auth(self):
        return self.share_token, ""

    def url_for(self, remote_path: str) -> str:
        safe = "/".join(quote(part, safe="") for part in remote_path.strip("/").split("/"))
        return self.base_url + safe

    def list_path(self, remote_path: str = "") -> list[RemoteEntry]:
        response = requests.request("PROPFIND", self.url_for(remote_path), auth=self.auth,
                                    headers={"Depth": "1"}, timeout=self.timeout)
        response.raise_for_status()
        return parse_propfind(response.content, remote_path)

    def competences(self) -> list[str]:
        return sorted((e.name for e in self.list_path() if e.is_directory and COMPETENCE_RE.fullmatch(e.name)), reverse=True)

    def files(self, competence: str) -> list[dict]:
        if not COMPETENCE_RE.fullmatch(competence):
            raise ValueError("Mês dos dados inválido. Use AAAA-MM.")
        items = [e.as_dict() for e in self.list_path(competence)]
        def order(item):
            match = ESTABLISHMENT_RE.fullmatch(item["name"])
            return (0, int(match.group(1))) if match else (1, item["name"].lower())
        result = sorted((i for i in items if i["kind"] != "other"), key=order)
        for name, url in EXTERNAL_REFERENCES.items():
            result.append({"name": name, "path": url, "is_directory": False,
                           "size": None, "etag": None, "modified": None,
                           "kind": "reference"})
        return result


def _text(prop, name):
    node = prop.find(f"{{DAV:}}{name}")
    return node.text.strip() if node is not None and node.text else None


def parse_propfind(payload: bytes, requested_path: str = "") -> list[RemoteEntry]:
    root = ElementTree.fromstring(payload)
    entries = []
    requested = requested_path.strip("/")
    for response in root.findall("{DAV:}response"):
        href = response.find("{DAV:}href")
        prop = response.find("{DAV:}propstat/{DAV:}prop")
        if href is None or not href.text or prop is None:
            continue
        path = unquote(urlparse(href.text).path).split("/public.php/webdav/", 1)[-1].strip("/")
        if path == requested:
            continue
        resource = prop.find("{DAV:}resourcetype")
        size = _text(prop, "getcontentlength")
        modified = _text(prop, "getlastmodified")
        if modified:
            try: modified = parsedate_to_datetime(modified).astimezone().isoformat()
            except (TypeError, ValueError): pass
        entries.append(RemoteEntry(path.rsplit("/", 1)[-1], path,
                     resource is not None and resource.find("{DAV:}collection") is not None,
                     int(size) if size and size.isdigit() else None,
                     (_text(prop, "getetag") or "").strip('"') or None, modified))
    return entries
