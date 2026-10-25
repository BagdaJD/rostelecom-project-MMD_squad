"""Изолированный PostgreSQL для ML-проверок; не меняет службы/реестр/общую БД.

Принимает уже распакованный официальный комплект PostgreSQL с PostGIS.
Создаёт только собственный новый каталог, БД mmd_ml_test_* и marker-комментарий.
Реквизиты записываются локально; пароль не печатается.
"""

import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


def start_test_postgres(binaries, directory, *, port=55439):
    binaries, directory = Path(binaries).resolve(), Path(directory).resolve()
    marker = directory / "test-database.json"
    if marker.exists():
        raise ValueError("Каталог уже принадлежит тестовому экземпляру; используйте его реквизиты")
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Для initdb нужен новый пустой каталог")
    directory.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(30)
    token = secrets.token_hex(16)
    database = "mmd_ml_test_" + token[:12]
    password_file = directory / "init-password.txt"
    password_file.write_text(password, encoding="utf-8")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    environment = {
        **os.environ,
        "PATH": str(binaries / "bin") + os.pathsep + os.environ.get("PATH", ""),
    }

    def run(args):
        background = args[0] == "pg_ctl.exe" and args[-1] == "start"
        result = subprocess.run(
            [str(binaries / "bin" / args[0]), *args[1:]],
            env=environment,
            creationflags=flags,
            stdout=subprocess.DEVNULL if background else subprocess.PIPE,
            stderr=subprocess.DEVNULL if background else subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=60,
        )
        if result.returncode:
            raise RuntimeError(
                f"{args[0]} failed: {(result.stdout or '')[-2000:]} {(result.stderr or '')[-2000:]}"
            )
        return result

    data = directory / "data"
    run(
        [
            "initdb.exe",
            "-D",
            str(data),
            "-U",
            "mmd_test_owner",
            "-A",
            "scram-sha-256",
            "--pwfile",
            str(password_file),
            "--encoding=UTF8",
            "--locale=C",
        ]
    )
    run(
        [
            "pg_ctl.exe",
            "-D",
            str(data),
            "-l",
            str(directory / "postgres.log"),
            "-o",
            f"-p {port} -h 127.0.0.1",
            "-w",
            "start",
        ]
    )
    admin = URL.create(
        "postgresql+psycopg",
        username="mmd_test_owner",
        password=password,
        host="127.0.0.1",
        port=port,
        database="postgres",
    )
    engine = create_engine(
        admin,
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 5},
        hide_parameters=True,
    )
    with engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database}"'))
        connection.execute(text(f"COMMENT ON DATABASE {database} IS 'mmd-ml-test:{token}'"))
    engine.dispose()
    url = admin.set(database=database)
    engine = create_engine(url, hide_parameters=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION postgis"))
        versions = connection.execute(text("SELECT version(), PostGIS_Full_Version()")).one()
    engine.dispose()
    result = {
        "database_url": url.render_as_string(hide_password=False),
        "token": token,
        "port": port,
        "database": database,
        "data_directory": str(data),
        "binaries": str(binaries),
        "versions": list(versions),
        "isolated": True,
    }
    marker.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return {k: result[k] for k in ("database", "port", "versions", "isolated")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binaries", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=55439)
    args = parser.parse_args()
    print(json.dumps(start_test_postgres(args.binaries, args.directory, port=args.port)))


if __name__ == "__main__":
    main()
