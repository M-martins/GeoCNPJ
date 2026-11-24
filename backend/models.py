from pydantic import BaseModel


class DownloadRequest(BaseModel):
    competence: str
    files: list[str]
    destination_root: str | None = None


class ImportRequest(BaseModel):
    competence: str
    folder: str


class RemoveRequest(BaseModel):
    delete_files: bool = False


class GeocodingRequest(BaseModel):
    process_job_id: str
    output_format: str = "csv"
    cores: int = 1
    resolve_ties: bool = True
    project_id: str | None = None


class ProcessRequest(BaseModel):
    competence: str
    uf: str
    municipality_code: str
    municipality_name: str
    active_only: bool = True
    output_format: str = "csv"
    project_id: str | None = None
    accept_incomplete: bool = False


class ProjectRequest(BaseModel):
    name: str
    competence: str | None = None


class ReviewRequest(BaseModel):
    reviewed: bool
    note: str = ""
