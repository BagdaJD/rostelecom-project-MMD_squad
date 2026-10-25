"""Запись разрешена только в отдельную БД с проверяемым marker-комментарием."""

import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def test_engine():
    raw_url = os.environ.get("MMD_TEST_DATABASE_URL")
    token = os.environ.get("MMD_TEST_DATABASE_TOKEN")
    if not raw_url or not token:
        raise RuntimeError("Нужны явные MMD_TEST_DATABASE_URL и MMD_TEST_DATABASE_TOKEN")
    url = make_url(raw_url)
    if not (url.database or "").startswith("mmd_ml_test_"):
        raise RuntimeError("Тесты разрешены только в выделенной mmd_ml_test_* БД")
    engine = create_engine(url, connect_args={"connect_timeout": 3}, hide_parameters=True)
    with engine.connect() as connection:
        database, marker = connection.execute(
            text(
                "SELECT datname, shobj_description(oid,'pg_database') FROM pg_database "
                "WHERE datname=current_database()"
            )
        ).one()
        if database != url.database or marker != f"mmd-ml-test:{token}":
            engine.dispose()
            raise RuntimeError("Маркер выделенной тестовой БД не совпал; запись запрещена")
    return engine


@contextmanager
def isolated_session():
    engine = test_engine()
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                    yield session
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
