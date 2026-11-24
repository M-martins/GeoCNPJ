from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from pathlib import Path
from typing import Dict, Any
from datetime import datetime
import pandas as pd
import shutil, uuid, json, subprocess, zipfile, os, re, hashlib, sys, threading, signal

app = FastAPI(title="GeoCNPJ - Motor Python")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8092", "http://localhost:8092"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
RUNTIME_DIR = Path(os.environ.get("GEOCNPJ_GEO_RUNTIME_DIR", str(Path.home() / "geocnpj_geo_python_runtime")))
UPLOADS = RUNTIME_DIR / "uploads"
JOBS_DIR = RUNTIME_DIR / "jobs"
CACHE_DIR = RUNTIME_DIR / "cache"
GEOCNPJ_CACHE_PATH = CACHE_DIR / "cache_geocnpj_enderecos.parquet"

for d in [RUNTIME_DIR, UPLOADS, JOBS_DIR, CACHE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

JOB_CONTROL_LOCK = threading.Lock()
CANCEL_EVENTS = {}
RUNNING_CHILDREN = {}


class JobCancelled(Exception):
    pass


def check_cancelled(job_id):
    with JOB_CONTROL_LOCK:
        event = CANCEL_EVENTS.get(job_id)
    if event is not None and event.is_set():
        raise JobCancelled


def stop_child(process):
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True, timeout=20, check=False)
    else:
        os.killpg(process.pid, signal.SIGTERM)



def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def status_label(status):
    return {
        "queued": "Na fila",
        "running": "Em execução",
        "cancelling": "Interrompendo",
        "cancelled": "Interrompido",
        "completed": "Concluído",
        "error": "Erro",
    }.get(str(status), str(status))


def slug(text):
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(text).lower())).strip("_") or "sem_nome"


def status_path(job_dir):
    return job_dir / "status.json"


def save_status(job_dir: Path, status: Dict[str, Any]):
    status["status_label"] = status_label(status.get("status"))
    status["ultima_atualizacao"] = now_iso()
    tmp = status_path(job_dir).with_suffix(".tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(status_path(job_dir))


def load_status(job_dir: Path):
    if not status_path(job_dir).exists():
        raise HTTPException(status_code=404, detail="Job não encontrado.")
    status = json.loads(status_path(job_dir).read_text(encoding="utf-8"))
    status["status_label"] = status_label(status.get("status"))
    return status


def add_log(job_dir, status, msg):
    line = f"{now_iso()} - {msg}"
    with (job_dir / "logs.txt").open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    logs = status.get("logs", [])
    logs.append(line)
    status["logs"] = logs[-150:]
    save_status(job_dir, status)


def set_stage(job_dir, status, stage, message):
    status["stage"] = stage
    add_log(job_dir, status, message)


def fingerprint(path):
    h = hashlib.sha256()
    st = path.stat()
    with path.open("rb") as f:
        h.update(f.read(1024 * 1024))
        if st.st_size > 1024 * 1024:
            f.seek(max(st.st_size - 1024 * 1024, 0))
            h.update(f.read(1024 * 1024))
    return {"filename": path.name, "size_bytes": int(st.st_size), "fingerprint": h.hexdigest()}


def read_input(path):
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    try:
        return pd.read_csv(path, sep=";", dtype=str, encoding="utf-8-sig")
    except Exception:
        return pd.read_csv(path, sep=",", dtype=str, encoding="utf-8-sig")


def prepare_addresses(df):
    required = ["tipo_logradouro", "logradouro", "numero", "bairro", "cep", "uf", "municipio_nome"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError("Colunas obrigatórias ausentes: " + ", ".join(missing))

    work = df.copy()
    work["_geo_row_id"] = range(len(work))

    for col in required:
        work[col] = work[col].fillna("").astype(str).str.strip()

    work["cep"] = work["cep"].str.replace(r"\D", "", regex=True)
    work.loc[work["cep"].ne(""), "cep"] = work.loc[work["cep"].ne(""), "cep"].str.zfill(8)
    work["numero"] = work["numero"].replace({"0": "", "S/N": "", "SN": "", "S N": ""})

    work["logradouro_geocode"] = (
        work["tipo_logradouro"] + " " + work["logradouro"]
    ).str.replace(r"\s+", " ", regex=True).str.strip()

    work["numero_geocode"] = work["numero"]
    work["bairro_geocode"] = work["bairro"]
    work["cep_geocode"] = work["cep"]
    work["municipio_geocode"] = work["municipio_nome"]
    work["uf_geocode"] = work["uf"]

    work["endereco_chave"] = (
        work["logradouro_geocode"].str.upper() + "|" +
        work["numero_geocode"].str.upper() + "|" +
        work["bairro_geocode"].str.upper() + "|" +
        work["cep_geocode"].str.upper() + "|" +
        work["municipio_geocode"].str.upper() + "|" +
        work["uf_geocode"].str.upper()
    )

    unique = (
        work[[
            "endereco_chave",
            "logradouro_geocode",
            "numero_geocode",
            "bairro_geocode",
            "cep_geocode",
            "municipio_geocode",
            "uf_geocode",
        ]]
        .drop_duplicates("endereco_chave")
        .reset_index(drop=True)
    )

    unique["endereco_usado_geocode"] = (
        unique["logradouro_geocode"] + ", " +
        unique["numero_geocode"] + ", " +
        unique["bairro_geocode"] + ", " +
        unique["municipio_geocode"] + " - " +
        unique["uf_geocode"] + ", " +
        unique["cep_geocode"]
    ).str.replace(r"\s+", " ", regex=True).str.strip(" ,")

    return work, unique


def detect_latlon(df):
    lower = {c.lower(): c for c in df.columns}
    lon = next((lower[c] for c in ["lon", "long", "longitude", "x", "lng"] if c in lower), None)
    lat = next((lower[c] for c in ["lat", "latitude", "y"] if c in lower), None)

    if not lon:
        lon = next((c for c in df.columns if "lon" in c.lower() or c.lower() == "x"), None)
    if not lat:
        lat = next((c for c in df.columns if "lat" in c.lower() or c.lower() == "y"), None)

    return lat, lon


def _to_num(series):
    return pd.to_numeric(series.astype(str).str.replace(",", ".", regex=False), errors="coerce")


def _precision_rank(value):
    text = str(value or "").lower()
    if any(x in text for x in ["exato", "numero", "número", "door", "rooftop", "ponto"]):
        return 1
    if any(x in text for x in ["segmento", "trecho", "street", "logradouro"]):
        return 2
    if any(x in text for x in ["cep", "postal"]):
        return 3
    if any(x in text for x in ["bairro", "localidade"]):
        return 4
    if any(x in text for x in ["municipio", "município", "cidade"]):
        return 5
    if text.strip():
        return 6
    return 9


def normalize_geocode_result(geo_raw, job_dir):
    geo = geo_raw.copy()

    if "endereco_chave" not in geo.columns:
        raise RuntimeError("Resultado do geocodebr não trouxe endereco_chave.")

    lat_col, lon_col = detect_latlon(geo)
    geo["latitude"] = geo[lat_col] if lat_col else ""
    geo["longitude"] = geo[lon_col] if lon_col else ""

    lat_num = _to_num(geo["latitude"].fillna(""))
    lon_num = _to_num(geo["longitude"].fillna(""))
    valid_coord = lat_num.between(-90, 90) & lon_num.between(-180, 180)
    geo["geocode_status"] = valid_coord.map({True: "encontrado", False: "nao_encontrado"})

    if "empate" in geo.columns:
        geo.loc[
            valid_coord & geo["empate"].astype(str).str.lower().isin(["true", "t", "1", "sim"]),
            "geocode_status",
        ] = "encontrado_com_empate"

    counts = geo.groupby("endereco_chave").size().rename("qtd_candidatos").reset_index()
    geo = geo.merge(counts, on="endereco_chave", how="left")

    geo["qtd_candidatos"] = geo["qtd_candidatos"].fillna(1).astype(int)

    geo["_tem_coord"] = valid_coord.astype(int)

    geo["_empate_rank"] = (
        geo["empate"].astype(str).str.lower().isin(["true", "t", "1", "sim"]).astype(int)
        if "empate" in geo.columns else 0
    )

    if "desvio_metros" in geo.columns:
        geo["_desvio_rank"] = _to_num(geo["desvio_metros"]).fillna(999999999)
    elif "distancia" in geo.columns:
        geo["_desvio_rank"] = _to_num(geo["distancia"]).fillna(999999999)
    else:
        geo["_desvio_rank"] = 999999999

    geo["_precisao_rank"] = geo["precisao"].apply(_precision_rank) if "precisao" in geo.columns else 9

    empates = geo[geo["qtd_candidatos"] > 1].copy()
    if not empates.empty:
        cols = [
            c for c in [
                "endereco_chave", "qtd_candidatos", "endereco_usado_geocode",
                "latitude", "longitude", "precisao", "desvio_metros",
                "empate", "endereco_encontrado"
            ] if c in empates.columns
        ]
        empates[cols].to_csv(job_dir / "relatorio_empates.csv", sep=";", index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(columns=["endereco_chave", "qtd_candidatos"]).to_csv(
            job_dir / "relatorio_empates.csv", sep=";", index=False, encoding="utf-8-sig"
        )

    return geo


def escolher_melhor_candidato(geo):
    sort_cols = ["endereco_chave", "_tem_coord", "_empate_rank", "_desvio_rank", "_precisao_rank"]
    geo_sorted = geo.sort_values(by=sort_cols, ascending=[True, False, True, True, True])
    chosen = geo_sorted.drop_duplicates("endereco_chave", keep="first").copy()
    chosen = chosen.drop(columns=[c for c in chosen.columns if c.startswith("_")], errors="ignore")
    return chosen


def limpar_colunas_auxiliares(df):
    return df.drop(columns=[c for c in df.columns if c.startswith("_")], errors="ignore")


def calcular_score_geocode(row):
    status = str(row.get("geocode_status", "")).lower()
    if not status.startswith("encontrado"):
        return 0

    score = 60
    precisao = str(row.get("precisao", "")).lower()

    if any(x in precisao for x in ["exato", "numero", "número", "door", "rooftop", "ponto"]):
        score = 100
    elif any(x in precisao for x in ["segmento", "trecho", "street", "logradouro"]):
        score = 85
    elif any(x in precisao for x in ["cep", "postal"]):
        score = 70
    elif any(x in precisao for x in ["bairro", "localidade"]):
        score = 50
    elif any(x in precisao for x in ["municipio", "município", "cidade"]):
        score = 30

    desvio = None
    for col in ["desvio_metros", "distancia"]:
        if col in row.index:
            try:
                raw = str(row.get(col, "")).replace(",", ".")
                if raw.strip():
                    desvio = float(raw)
                break
            except Exception:
                pass

    if desvio is not None:
        if desvio <= 30:
            pass
        elif desvio <= 100:
            score -= 10
        elif desvio <= 500:
            score -= 25
        else:
            score -= 40

    try:
        qtd = int(float(str(row.get("qtd_candidatos", 1)).replace(",", ".")))
    except Exception:
        qtd = 1

    if qtd > 1:
        score -= 10

    if str(row.get("empate", "")).lower() in ["true", "t", "1", "sim"]:
        score -= 10

    return max(0, min(100, int(score)))


def decidir_geocode(row):
    status = str(row.get("geocode_status", "")).lower()
    score = int(row.get("score_geocode", 0) or 0)

    try:
        qtd = int(float(str(row.get("qtd_candidatos", 1)).replace(",", ".")))
    except Exception:
        qtd = 1

    if not status.startswith("encontrado") or score == 0:
        return "nao_encontrado"
    if qtd > 1 and score < 85:
        return "revisar_empate"
    if score >= 85 and qtd <= 1:
        return "aceito_automaticamente"
    if score >= 75:
        return "aceito_com_alerta"
    if qtd > 1:
        return "revisar_empate"
    return "revisar_baixa_precisao"


def aplicar_score_e_decisao(df):
    out = df.copy()
    out["score_geocode"] = out.apply(calcular_score_geocode, axis=1)
    out["decisao_geocode"] = out.apply(decidir_geocode, axis=1)
    out["necessita_revisao"] = out["decisao_geocode"].isin([
        "revisar_empate", "revisar_baixa_precisao", "nao_encontrado"
    ])
    return out


def carregar_cache_geocnpj():
    if GEOCNPJ_CACHE_PATH.exists():
        try:
            return pd.read_parquet(GEOCNPJ_CACHE_PATH)
        except Exception:
            pass

    return pd.DataFrame(columns=[
        "endereco_chave", "latitude", "longitude", "geocode_status",
        "precisao", "desvio_metros", "empate", "endereco_encontrado",
        "endereco_usado_geocode", "qtd_candidatos", "score_geocode",
        "decisao_geocode", "necessita_revisao", "cache_updated_at"
    ])


def salvar_cache_geocnpj(cache_df):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if cache_df.empty:
        cache_df.to_parquet(GEOCNPJ_CACHE_PATH, index=False)
        return
    cache_df = cache_df.drop_duplicates("endereco_chave", keep="last")
    cache_df.to_parquet(GEOCNPJ_CACHE_PATH, index=False)


def separar_por_cache(unique):
    cache = carregar_cache_geocnpj()
    if cache.empty or "endereco_chave" not in cache.columns:
        return unique.copy(), cache.iloc[0:0].copy(), cache

    input_keys = set(unique["endereco_chave"].astype(str))
    cache_keys = set(cache["endereco_chave"].astype(str))

    novos = unique[~unique["endereco_chave"].astype(str).isin(cache_keys)].copy()
    reaproveitados = cache[cache["endereco_chave"].astype(str).isin(input_keys)].copy()

    return novos, reaproveitados, cache


def atualizar_cache(cache_atual, geo_chosen):
    if geo_chosen is None or geo_chosen.empty:
        return cache_atual

    cols = [
        "endereco_chave", "latitude", "longitude", "geocode_status",
        "precisao", "desvio_metros", "empate", "endereco_encontrado",
        "endereco_usado_geocode", "qtd_candidatos", "score_geocode",
        "decisao_geocode", "necessita_revisao"
    ]
    cols = [c for c in cols if c in geo_chosen.columns]
    novos = geo_chosen[cols].copy()
    novos["cache_updated_at"] = now_iso()

    combined = pd.concat([cache_atual, novos], ignore_index=True, sort=False)
    combined = combined.drop_duplicates("endereco_chave", keep="last")
    salvar_cache_geocnpj(combined)
    return combined



def limpar_valor_geojson(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float):
        if value == float("inf") or value == float("-inf"):
            return None
    return value


def criar_geojson(df, output_path):
    """Write complete GeoJSON incrementally, retaining every source property."""
    def coordinate(column):
        values = df[column] if column in df else pd.Series("", index=df.index)
        return pd.to_numeric(values.astype(str).str.replace(",", ".", regex=False).str.strip(), errors="coerce")

    latitude = coordinate("latitude")
    longitude = coordinate("longitude")
    valid = latitude.between(-90, 90) & longitude.between(-180, 180)
    count = int(valid.sum())
    metadata = {
        "total_registros_csv": int(len(df)),
        "total_features_geojson": count,
        "total_sem_coordenada": int(len(df) - count),
        "observacao": "GeoJSON contém todos os campos do CSV geocodificado como properties."
    }
    header = {"type": "FeatureCollection", "name": output_path.stem,
              "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
              "metadata": metadata}
    temporary = output_path.with_name(output_path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as output:
            output.write(json.dumps(header, ensure_ascii=False)[:-1] + ', "features": [')
            first = True
            for position, (_, row) in enumerate(df.iterrows()):
                if not valid.iloc[position]:
                    continue
                props = {col: limpar_valor_geojson(row.get(col)) for col in df.columns}
                feature = {"type": "Feature", "geometry": {"type": "Point",
                           "coordinates": [float(longitude.iloc[position]), float(latitude.iloc[position])]},
                           "properties": props}
                if not first:
                    output.write(",")
                output.write(json.dumps(feature, ensure_ascii=False))
                first = False
            output.write("]}")
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return count

def make_preview(df):
    cols = [
        c for c in [
            "cnpj_completo", "nome_fantasia", "cnae_principal_classe",
            "endereco_usado_geocode", "geocode_status", "score_geocode",
            "decisao_geocode", "necessita_revisao", "latitude", "longitude",
            "precisao", "desvio_metros", "qtd_candidatos"
        ] if c in df.columns
    ]
    preview = df.head(20).fillna("").astype(str)
    if cols:
        preview = preview[cols]
    return {"columns": list(preview.columns), "rows": preview.to_dict(orient="records")}


def write_zip(job_dir, status, result_path):
    zip_path = job_dir / f"{status['nome_base']}_pacote_geocodificado.zip"
    files = [
        result_path,
        job_dir / f"{status['nome_base']}_pontos.geojson",
        job_dir / "enderecos_unicos.csv",
        job_dir / "enderecos_novos_geocodebr.csv",
        job_dir / "resultado_geocodebr_enderecos.csv",
        job_dir / "resultado_geocodebr_enderecos_completo.csv",
        job_dir / "resultado_geocodebr_enderecos_novos.csv",
        job_dir / "relatorio_geocodificacao.csv",
        job_dir / "relatorio_decisao.csv",
        job_dir / "relatorio_empates.csv",
        job_dir / "relatorio_revisao.csv",
        job_dir / "relatorio_nao_encontrados.csv",
        job_dir / "resumo_geocodificacao.csv",
        job_dir / "parametros_job.json",
        job_dir / "python_stdout.txt",
        job_dir / "python_stderr.txt",
    ]

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for file in files:
            if file.exists():
                z.write(file, file.name)

    return zip_path


def export_reports(job_dir, merged):
    rel_status = merged["geocode_status"].fillna("nao_encontrado").value_counts().reset_index()
    rel_status.columns = ["geocode_status", "quantidade"]
    rel_status.to_csv(job_dir / "relatorio_geocodificacao.csv", sep=";", index=False, encoding="utf-8-sig")

    rel_decisao = merged["decisao_geocode"].fillna("sem_decisao").value_counts().reset_index()
    rel_decisao.columns = ["decisao_geocode", "quantidade"]
    rel_decisao.to_csv(job_dir / "relatorio_decisao.csv", sep=";", index=False, encoding="utf-8-sig")

    cols = [
        c for c in [
            "cnpj_completo", "nome_fantasia", "endereco_usado_geocode",
            "geocode_status", "score_geocode", "decisao_geocode",
            "qtd_candidatos", "latitude", "longitude", "precisao",
            "desvio_metros", "empate", "endereco_encontrado",
            "tipo_logradouro", "logradouro", "numero", "bairro",
            "cep", "municipio_nome", "uf"
        ] if c in merged.columns
    ]

    merged[merged["necessita_revisao"] == True][cols].to_csv(
        job_dir / "relatorio_revisao.csv", sep=";", index=False, encoding="utf-8-sig"
    )
    merged[merged["geocode_status"] == "nao_encontrado"][cols].to_csv(
        job_dir / "relatorio_nao_encontrados.csv", sep=";", index=False, encoding="utf-8-sig"
    )


def run_job(job_id):
    job_dir = JOBS_DIR / job_id
    status = load_status(job_dir)

    try:
        check_cancelled(job_id)
        status["status"] = "running"
        status["inicio"] = now_iso()
        save_status(job_dir, status)

        resolver_empates = bool(status.get("resolver_empates"))
        set_stage(job_dir, status, "reading", "Lendo arquivo de entrada...")

        input_path = Path(status["input_path"])
        df_input = read_input(input_path)
        check_cancelled(job_id)
        status["total_registros_entrada"] = int(len(df_input))
        save_status(job_dir, status)
        add_log(job_dir, status, f"Registros de entrada: {len(df_input)}")

        set_stage(job_dir, status, "preparing", "Organizando e deduplicando endereços...")
        base_df, unique = prepare_addresses(df_input)
        check_cancelled(job_id)
        unique.to_csv(job_dir / "enderecos_unicos.csv", sep=";", index=False, encoding="utf-8-sig")

        status["total_enderecos_unicos"] = int(len(unique))
        save_status(job_dir, status)
        add_log(job_dir, status, f"Endereços únicos: {len(unique)}")

        set_stage(job_dir, status, "cache", "Conferindo endereços já processados no cache local...")
        novos, cache_reaproveitado, cache_atual = separar_por_cache(unique)
        check_cancelled(job_id)

        status["enderecos_em_cache"] = int(len(cache_reaproveitado))
        status["enderecos_novos_para_geocodebr"] = int(len(novos))
        save_status(job_dir, status)

        add_log(job_dir, status, f"Endereços reaproveitados do cache próprio: {len(cache_reaproveitado)}")
        add_log(job_dir, status, f"Endereços novos enviados ao geocodebr: {len(novos)}")

        if len(novos) > 0:
            novos_path = job_dir / "enderecos_novos_geocodebr.csv"
            novos_geo_path = job_dir / "resultado_geocodebr_enderecos_novos.csv"
            novos.to_csv(novos_path, sep=";", index=False, encoding="utf-8-sig")

            set_stage(job_dir, status, "matching", f"Comparando {len(novos):,} endereços novos com o CNEFE pelo geocodebr. Esta fase pode levar mais tempo.")
            cmd = [
                sys.executable,
                str(BASE_DIR / "python_scripts" / "run_geocodebr.py"),
                str(novos_path),
                str(novos_geo_path),
                str(CACHE_DIR),
                str(status.get("n_cores", 1)),
                "true" if resolver_empates else "false",
            ]

            check_cancelled(job_id)
            proc = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            with JOB_CONTROL_LOCK:
                RUNNING_CHILDREN[job_id] = proc
            try:
                check_cancelled(job_id)
                stdout, stderr = proc.communicate()
            finally:
                with JOB_CONTROL_LOCK:
                    RUNNING_CHILDREN.pop(job_id, None)
                if proc.poll() is None:
                    stop_child(proc)
                    proc.communicate()
            check_cancelled(job_id)
            (job_dir / "python_stdout.txt").write_text(stdout or "", encoding="utf-8")
            (job_dir / "python_stderr.txt").write_text(stderr or "", encoding="utf-8")

            if proc.returncode != 0:
                raise RuntimeError(
                    "Falha ao executar geocodebr via Python. "
                    + (stderr or stdout or "")[:2500]
                )

            geo_raw_new = pd.read_csv(novos_geo_path, sep=";", dtype=str, encoding="utf-8-sig")
        else:
            geo_raw_new = pd.DataFrame(columns=["endereco_chave"])
            pd.DataFrame(columns=["endereco_chave"]).to_csv(
                job_dir / "enderecos_novos_geocodebr.csv", sep=";", index=False, encoding="utf-8-sig"
            )
            pd.DataFrame(columns=["endereco_chave"]).to_csv(
                job_dir / "resultado_geocodebr_enderecos_novos.csv", sep=";", index=False, encoding="utf-8-sig"
            )
            (job_dir / "python_stdout.txt").write_text("Nenhum endereço novo. Cache próprio reutilizado.\n", encoding="utf-8")
            (job_dir / "python_stderr.txt").write_text("", encoding="utf-8")

        check_cancelled(job_id)
        set_stage(job_dir, status, "merging", "Conferindo candidatos e reunindo os resultados...")
        if len(geo_raw_new) > 0:
            geo_raw_norm = normalize_geocode_result(geo_raw_new, job_dir)
            limpar_colunas_auxiliares(geo_raw_norm).to_csv(
                job_dir / "resultado_geocodebr_enderecos_completo.csv",
                sep=";", index=False, encoding="utf-8-sig",
            )
            geo_chosen_new = aplicar_score_e_decisao(escolher_melhor_candidato(geo_raw_norm))
            atualizar_cache(cache_atual, geo_chosen_new)
        else:
            geo_raw_norm = pd.DataFrame(columns=["endereco_chave"])
            geo_chosen_new = pd.DataFrame(columns=["endereco_chave"])
            pd.DataFrame(columns=["endereco_chave"]).to_csv(
                job_dir / "resultado_geocodebr_enderecos_completo.csv", sep=";", index=False, encoding="utf-8-sig"
            )
            pd.DataFrame(columns=["endereco_chave", "qtd_candidatos"]).to_csv(
                job_dir / "relatorio_empates.csv", sep=";", index=False, encoding="utf-8-sig"
            )

        # Para o modo automático: usa 1 candidato por endereço.
        # Para o modo revisão: usa todos os candidatos novos e todos os candidatos disponíveis do cache como 1 por endereço.
        # Observação: cache próprio guarda candidato escolhido; candidatos múltiplos só aparecem quando o endereço foi geocodificado no job atual.
        if resolver_empates:
            geo_final = pd.concat([cache_reaproveitado, geo_chosen_new], ignore_index=True, sort=False)
            geo_final = geo_final.drop_duplicates("endereco_chave", keep="last")
        else:
            geo_raw_ready = aplicar_score_e_decisao(limpar_colunas_auxiliares(geo_raw_norm)) if len(geo_raw_norm) > 0 else geo_raw_norm
            geo_final = pd.concat([cache_reaproveitado, geo_raw_ready], ignore_index=True, sort=False)

        geo_final.to_csv(job_dir / "resultado_geocodebr_enderecos.csv", sep=";", index=False, encoding="utf-8-sig")

        keep = [
            c for c in [
                "endereco_chave", "latitude", "longitude", "geocode_status",
                "precisao", "desvio_metros", "empate", "endereco_encontrado",
                "endereco_usado_geocode", "qtd_candidatos", "score_geocode",
                "decisao_geocode", "necessita_revisao"
            ] if c in geo_final.columns
        ]

        if resolver_empates:
            before = len(base_df)
            merged = base_df.merge(geo_final[keep], on="endereco_chave", how="left", validate="many_to_one")
            if len(merged) != before:
                raise RuntimeError(f"Quantidade de linhas alterada no modo automático. Antes={before}, Depois={len(merged)}.")
            merged["tipo_saida_geocode"] = "candidato_escolhido"
        else:
            merged = base_df.merge(geo_final[keep], on="endereco_chave", how="left")
            merged["tipo_saida_geocode"] = merged["qtd_candidatos"].apply(
                lambda x: "candidato_empate" if pd.notna(x) and str(x) not in ["", "1", "1.0"] else "candidato_unico"
            )

        merged["geocode_status"] = merged["geocode_status"].fillna("nao_encontrado")
        if "latitude" not in merged:
            merged["latitude"] = ""
        if "longitude" not in merged:
            merged["longitude"] = ""
        if "qtd_candidatos" not in merged:
            merged["qtd_candidatos"] = 0

        # Garante score no resultado final, inclusive para linhas sem match.
        merged = aplicar_score_e_decisao(merged)

        check_cancelled(job_id)
        set_stage(job_dir, status, "exporting", "Gravando a base geocodificada e o GeoJSON...")
        fmt = status.get("formato_saida", "csv")
        result_path = job_dir / f"{status['nome_base']}_geocodificado.{fmt}"

        if fmt == "parquet":
            merged.to_parquet(result_path, index=False)
        else:
            merged.to_csv(result_path, sep=";", index=False, encoding="utf-8-sig")

        geojson_path = job_dir / f"{status['nome_base']}_pontos.geojson"
        total_geojson = criar_geojson(merged, geojson_path)

        total = len(merged)
        encontrados = int(merged["geocode_status"].astype(str).str.startswith("encontrado").sum())
        total_revisao = int((merged["necessita_revisao"] == True).sum())
        score_medio = round(float(pd.to_numeric(merged["score_geocode"], errors="coerce").fillna(0).mean()), 2)

        total_enderecos_com_empate = 0
        if "qtd_candidatos" in geo_final.columns and len(geo_final) > 0:
            total_enderecos_com_empate = int((pd.to_numeric(geo_final["qtd_candidatos"], errors="coerce").fillna(1) > 1).sum())

        resumo = {
            "modo_resolver_empates": resolver_empates,
            "total_registros_entrada": int(len(df_input)),
            "total_registros_saida": int(total),
            "total_enderecos_unicos": int(len(unique)),
            "enderecos_reaproveitados_cache": int(len(cache_reaproveitado)),
            "enderecos_novos_geocodebr": int(len(novos)),
            "candidatos_brutos_geocodebr_novos": int(len(geo_raw_new)),
            "enderecos_com_empate": total_enderecos_com_empate,
            "registros_com_coordenada": encontrados,
            "registros_sem_coordenada": int(total - encontrados),
            "taxa_registros_com_coordenada": round(encontrados / total * 100, 2) if total else 0,
            "score_medio": score_medio,
            "necessitam_revisao": total_revisao,
            "pontos_geojson": int(total_geojson),
            "geojson_completo_atributos": True,
            "geojson_crs": "EPSG:4326",
        }

        pd.DataFrame([{"indicador": k, "valor": v} for k, v in resumo.items()]).to_csv(
            job_dir / "resumo_geocodificacao.csv", sep=";", index=False, encoding="utf-8-sig"
        )

        export_reports(job_dir, merged)

        parametros = {
            **status,
            "fim": now_iso(),
            "resumo": resumo,
            "cache_geocnpj_enderecos": str(GEOCNPJ_CACHE_PATH),
        }

        (job_dir / "parametros_job.json").write_text(
            json.dumps(parametros, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        check_cancelled(job_id)
        set_stage(job_dir, status, "packaging", "Montando o pacote final para download...")
        package_path = write_zip(job_dir, status, result_path)
        check_cancelled(job_id)

        status.update({
            "status": "completed",
            "stage": "completed",
            "fim": now_iso(),
            "arquivo_pacote": package_path.name,
            "download_url": f"/download-job/{job_id}/{package_path.name}",
            "resumo": resumo,
            "preview": make_preview(merged),
        })

        save_status(job_dir, status)
        add_log(job_dir, status, f"Processamento concluído. Pacote: {package_path.name}")

    except JobCancelled:
        status = load_status(job_dir)
        status["status"] = "cancelled"
        status["fim"] = now_iso()
        save_status(job_dir, status)
        add_log(job_dir, status, "Geocodificação interrompida pelo usuário; arquivos já criados foram preservados.")
    except Exception as exc:
        status = load_status(job_dir)
        status["status"] = "error"
        status["erro"] = str(exc)
        status["fim"] = now_iso()
        save_status(job_dir, status)
        add_log(job_dir, status, f"ERRO: {exc}")
    finally:
        with JOB_CONTROL_LOCK:
            CANCEL_EVENTS.pop(job_id, None)
            RUNNING_CHILDREN.pop(job_id, None)


MAX_UPLOAD_BYTES = int(os.getenv("GEOCNPJ_MAX_UPLOAD_BYTES", str(2 * 1024**3)))
UPLOAD_CHUNK_BYTES = 1024 * 1024


def save_upload(source, destination: Path, max_bytes: int = MAX_UPLOAD_BYTES):
    """Copy an uploaded file with a hard byte limit and no partial destination."""
    size = 0
    try:
        with destination.open("xb") as target:
            while chunk := source.read(UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("Arquivo acima do limite de upload configurado.")
                target.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return size


@app.post("/jobs")
async def create_job(
    background_tasks: BackgroundTasks,
    arquivo: UploadFile = File(...),
    formato_saida: str = Form("csv"),
    n_cores: int = Form(1),
    resolver_empates: bool = Form(True),
):
    if Path(arquivo.filename or "").suffix.lower() not in {".csv", ".parquet"}:
        raise HTTPException(400, "Envie um arquivo CSV ou Parquet.")
    job_id = str(uuid.uuid4())[:8]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    safe_name = re.sub(r'[<>:"/\\|?*]+', "_", Path(arquivo.filename or f"entrada_{job_id}.csv").name)
    upload_path = UPLOADS / f"{job_id}_{safe_name}"

    try:
        await run_in_threadpool(save_upload, arquivo.file, upload_path)
    except ValueError as exc:
        job_dir.rmdir()
        raise HTTPException(413, str(exc)) from exc
    except Exception:
        job_dir.rmdir()
        raise

    nome_base = f"geocnpj_{slug(upload_path.stem)}_{job_id}"

    status = {
        "job_id": job_id,
        "status": "queued",
        "input_path": str(upload_path),
        "input_filename": safe_name,
        "input_fingerprint": fingerprint(upload_path),
        "nome_base": nome_base,
        "formato_saida": formato_saida if formato_saida in ["csv", "parquet"] else "csv",
        "n_cores": min(max(int(n_cores), 1), os.cpu_count() or 1),
        "resolver_empates": bool(resolver_empates),
        "criado_em": now_iso(),
        "logs": [],
    }

    save_status(job_dir, status)
    add_log(job_dir, status, "Job criado.")

    with JOB_CONTROL_LOCK:
        CANCEL_EVENTS[job_id] = threading.Event()
    background_tasks.add_task(run_job, job_id)

    return {"job_id": job_id, "status_url": f"/jobs/{job_id}"}


def safe_job_dir(job_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{8}", job_id):
        raise HTTPException(status_code=404, detail="Job não encontrado.")
    return JOBS_DIR / job_id


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job_dir = safe_job_dir(job_id)
    status = load_status(job_dir)
    if status.get("status") in {"completed", "cancelled", "error"}:
        return status
    with JOB_CONTROL_LOCK:
        event = CANCEL_EVENTS.setdefault(job_id, threading.Event())
        event.set()
        process = RUNNING_CHILDREN.get(job_id)
    status["status"] = "cancelling"
    add_log(job_dir, status, "Interrupção solicitada pelo usuário.")
    stop_child(process)
    return load_status(job_dir)


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    return load_status(safe_job_dir(job_id))


@app.get("/jobs")
def list_jobs():
    jobs = []
    for job_dir in sorted(JOBS_DIR.glob("*"), reverse=True):
        if not job_dir.is_dir():
            continue
        try:
            status = load_status(job_dir)
            jobs.append({
                "job_id": status.get("job_id"),
                "status": status.get("status"),
                "status_label": status.get("status_label"),
                "input_filename": status.get("input_filename"),
                "criado_em": status.get("criado_em"),
                "resumo": status.get("resumo"),
                "download_url": status.get("download_url"),
            })
        except Exception:
            pass
    return jobs[:50]


@app.get("/download-job/{job_id}/{filename}")
def download_job(job_id: str, filename: str):
    folder = safe_job_dir(job_id)
    path = folder / filename
    if Path(filename).name != filename or path.is_symlink() or path.resolve().parent != folder.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return FileResponse(path, filename=filename, media_type="application/octet-stream")


@app.get("/runtime-info")
def runtime_info():
    return {
        "runtime_dir": str(RUNTIME_DIR),
        "uploads": str(UPLOADS),
        "jobs": str(JOBS_DIR),
        "cache_geocodebr": str(CACHE_DIR),
        "cache_geocnpj_enderecos": str(GEOCNPJ_CACHE_PATH),
    }


@app.post("/check-python")
def check_python():
    try:
        from importlib.metadata import version
        package_version = version("geocodebr")
        from geocodebr import definir_campos, definir_pasta_cache, geocode
        return {
            "ok": True,
            "version": package_version,
            "message": "Python/geocodebr disponível",
        }
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
