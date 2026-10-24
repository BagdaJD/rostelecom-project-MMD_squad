"""CLI каркаса: пользователь, 2FA, загрузка демо-данных.

Примеры (из каталога backend/):
    python -m app.cli create-user --email a@example.com --role analyst
    python -m app.cli enable-2fa --email a@example.com
    python -m app.cli seed --bundle ../data/seed/demo_bundle.json
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from app.core.config import get_settings
from app.db.session import SessionLocal
from modules.auth import service as auth


def _password(args: argparse.Namespace) -> str:
    if args.password:
        return args.password
    value = getpass.getpass("Пароль: ")
    if len(value) < 8:
        sys.exit("Пароль короче 8 символов")
    return value


def cmd_create_user(args: argparse.Namespace) -> int:
    with SessionLocal() as session:
        user = auth.create_user(
            session, args.email, args.login or args.email, _password(args), args.role
        )
        session.commit()
        print(f"создан пользователь id={user.id} role={user.role}")
    return 0


def cmd_enable_2fa(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from app.models import User

    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.email == args.email))
        if user is None:
            sys.exit("пользователь не найден")
        secret, codes = auth.enable_2fa(session, user)
        session.commit()
        print(f"secret: {secret}")
        print("резервные коды (показываются один раз):")
        for code in codes:
            print(f"  {code}")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from ingestion.loader import load_bundle, read_bundle

    bundle_path = Path(args.bundle)
    if not bundle_path.exists():
        sys.exit(f"файл не найден: {bundle_path}")
    with SessionLocal() as session:
        result = load_bundle(session, read_bundle(bundle_path))
        session.commit()
        print("импорт завершён:", result.as_dict())
    return 0


def cmd_check_config(_: argparse.Namespace) -> int:
    settings = get_settings()
    problems = []
    if settings.secret_key.startswith("change-me"):
        problems.append("SECRET_KEY не изменён")
    if settings.totp_encryption_key.startswith("change-me"):
        problems.append("TOTP_ENCRYPTION_KEY не изменён")
    if problems:
        print("; ".join(problems))
        return 1
    print("конфигурация в порядке")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="Утилиты каркаса")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-user", help="создать учётную запись")
    p.add_argument("--email", required=True)
    p.add_argument("--login")
    p.add_argument("--role", default="manager", choices=("admin", "analyst", "manager"))
    p.add_argument("--password", help="иначе будет запрошен ввод")
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser("enable-2fa", help="включить TOTP и показать secret")
    p.add_argument("--email", required=True)
    p.set_defaults(func=cmd_enable_2fa)

    p = sub.add_parser("seed", help="загрузить демонстрационный набор")
    p.add_argument("--bundle", default="../data/seed/demo_bundle.json")
    p.set_defaults(func=cmd_seed)

    p = sub.add_parser("check-config", help="проверить обязательные переменные окружения")
    p.set_defaults(func=cmd_check_config)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
