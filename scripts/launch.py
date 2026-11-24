"""Set up a local Python environment and launch GeoCNPJ.

This script uses only the Python standard library before installing requirements.
It never downloads the CNPJ or CNEFE datasets; those are fetched by the app
only when the user starts the corresponding workflow.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"
ENV_DIR = ROOT / ".venv"
ENV_PYTHON = ENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
URL = "http://127.0.0.1:8092"
DIRECT_PACKAGES = {
    "fastapi": "0.165.0",
    "uvicorn": "0.54.0",
    "requests": "2.34.2",
    "httpx": "0.28.1",
    "pandas": "3.1.1",
    "pyarrow": "26.0.1",
    "send2trash": "2.2.0",
    "python-multipart": "0.0.34",
    "polars": "2.1.0",
    "polars-runtime-compat": "2.1.0",
    "geocodebr": "0.2.0",
}
REQUIRED_PROJECT_FILES = (
    REQUIREMENTS,
    ROOT / "frontend" / "home.html",
)


def check_python() -> None:
    if sys.version_info < (3, 11):
        raise RuntimeError("É necessário Python 3.11 ou superior. Instale Python e execute novamente.")


def check_project_files() -> None:
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_PROJECT_FILES if not path.is_file()]
    if missing:
        raise RuntimeError("Arquivos do projeto ausentes: " + ", ".join(missing))


def check_environment(python: Path) -> tuple[bool, str]:
    if not python.is_file():
        return False, "Ambiente Python local ainda não existe."
    code = (
        "import importlib.metadata as m, json, sys; "
        "required=json.loads(sys.argv[1]); missing=[]; "
        "exec('for name, expected in required.items():\\n"
        " try:\\n  found=m.version(name)\\n"
        "  if expected and found != expected: missing.append(name + "
        "\" (versão \" + found + \"; esperada \" + expected + \")\")\\n"
        " except m.PackageNotFoundError: missing.append(name)'); "
        "print('\\n'.join(missing)); sys.exit(bool(missing))"
    )
    try:
        result = subprocess.run(
            [str(python), "-c", code, json.dumps(DIRECT_PACKAGES)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if result.returncode:
            detail = result.stdout.strip() or result.stderr.strip() or "Pacotes ausentes ou ambiente inválido."
            return False, detail
        pip_check = subprocess.run(
            [str(python), "-m", "pip", "check"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if pip_check.returncode:
            return False, pip_check.stdout.strip() or pip_check.stderr.strip()
        return True, "Dependências verificadas."
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Não foi possível usar o ambiente local: {exc}"


def setup_environment() -> Path:
    check_python()
    if not ENV_PYTHON.is_file():
        print("Criando o ambiente Python local (.venv)...", flush=True)
        venv.EnvBuilder(with_pip=True).create(ENV_DIR)
    ok, message = check_environment(ENV_PYTHON)
    if ok:
        print(message, flush=True)
        return ENV_PYTHON
    print(f"Instalando/atualizando dependências: {message}", flush=True)
    print("Esta etapa requer internet na primeira execução e pode levar alguns minutos.", flush=True)
    subprocess.run(
        [str(ENV_PYTHON), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        cwd=ROOT, check=True,
    )
    ok, message = check_environment(ENV_PYTHON)
    if not ok:
        raise RuntimeError(f"A instalação terminou, mas a verificação falhou: {message}")
    print("Dependências instaladas e verificadas.", flush=True)
    return ENV_PYTHON


def health() -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(f"{URL}/api/health", timeout=2) as response:
            payload = json.load(response)
        return bool(payload.get("ok") and payload.get("app") == "GeoCNPJ" and Path(payload.get("project_root", "")).resolve() == ROOT.resolve()), str(payload.get("project_root") or payload.get("app") or "")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False, ""


def launch(python: Path, no_browser: bool) -> None:
    running, identity = health()
    if not running:
        if identity:
            raise RuntimeError(f"A porta 8092 já está ocupada por outra instalação ({identity}). Feche-a e tente novamente.")
        logs = ROOT / "logs"
        logs.mkdir(exist_ok=True)
        out = (logs / "server.out.log").open("a", encoding="utf-8")
        err = (logs / "server.err.log").open("a", encoding="utf-8")
        try:
            process = subprocess.Popen(
                [str(python), "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8092"],
                cwd=ROOT, stdout=out, stderr=err,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        finally:
            out.close()
            err.close()
        print("Iniciando o GeoCNPJ...", flush=True)
        for _ in range(60):
            running, identity = health()
            if running:
                break
            if process.poll() is not None:
                break
            time.sleep(0.5)
        if not running:
            raise RuntimeError("O servidor não iniciou. Consulte logs/server.err.log.")
    print(f"GeoCNPJ pronto em {URL}", flush=True)
    if not no_browser:
        webbrowser.open(URL)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepara e inicia o GeoCNPJ localmente.")
    parser.add_argument("--check", action="store_true", help="apenas verifica Python e dependências; não instala")
    parser.add_argument("--setup-only", action="store_true", help="prepara dependências, sem iniciar o servidor")
    parser.add_argument("--no-browser", action="store_true", help="inicia sem abrir o navegador")
    args = parser.parse_args()
    try:
        check_python()
        check_project_files()
        if args.check:
            ok, message = check_environment(ENV_PYTHON)
            print(message)
            return 0 if ok else 1
        python = setup_environment()
        if not args.setup_only:
            launch(python, args.no_browser)
        return 0
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
