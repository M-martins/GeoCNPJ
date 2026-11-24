import json
import re
from pathlib import Path


def stream_geojson(path: Path):
    """Use the faster standard parser for small files and bounded memory for large files."""
    if path.stat().st_size <= 4 * 1024 * 1024:
        data = json.loads(path.read_text(encoding="utf-8"))
        yield "metadata", data.get("metadata", {})
        for feature in data.get("features", []):
            yield "feature", feature
        return
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8") as source:
        buffer = ""
        while True:
            match = re.search(r',\s*"features"\s*:\s*\[', buffer)
            if match:
                break
            chunk = source.read(64 * 1024)
            if not chunk or len(buffer) > 8 * 1024 * 1024:
                raise ValueError("GeoJSON sem lista de feicoes reconhecivel.")
            buffer += chunk
        header = json.loads(buffer[:match.start()] + "}")
        yield "metadata", header.get("metadata", {})
        buffer = buffer[match.end():]
        while True:
            buffer = buffer.lstrip()
            if buffer.startswith("]"):
                return
            if buffer.startswith(","):
                buffer = buffer[1:].lstrip()
            try:
                feature, end = decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                chunk = source.read(64 * 1024)
                if not chunk:
                    raise ValueError("GeoJSON truncado ou invalido.") from None
                buffer += chunk
                continue
            if not isinstance(feature, dict):
                raise ValueError("Feicao GeoJSON invalida.")
            yield "feature", feature
            buffer = buffer[end:]
