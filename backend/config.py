import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    frontend_dir: Path
    data_dir: Path
    webdav_url: str
    share_token: str
    geo_api_url: str
    geo_project_dir: Path
    auto_resume: bool
    lease_seconds: int

    @classmethod
    def from_env(cls):
        base = Path(__file__).resolve().parent.parent
        return cls(
            base_dir=base,
            frontend_dir=base / "frontend",
            data_dir=Path(os.getenv("GEOCNPJ_DATA_DIR") or os.getenv("GEOCNPJ_V2_DATA_DIR") or str(base / "data")).resolve(),
            webdav_url=os.getenv("RECEITA_WEBDAV_URL", "https://arquivos.receitafederal.gov.br/public.php/webdav/"),
            share_token=os.getenv("RECEITA_SHARE_TOKEN", "YggdBLfdninEJX9"),
            geo_api_url=os.getenv("GEOCNPJ_GEO_API_URL", "http://127.0.0.1:8092/geo"),
            geo_project_dir=base / "geo_engine",
            auto_resume=os.getenv("GEOCNPJ_AUTO_RESUME", "0").strip().lower() in {"1", "true", "yes", "sim"},
            lease_seconds=max(15, int(os.getenv("GEOCNPJ_LEASE_SECONDS", "45"))),
        )
