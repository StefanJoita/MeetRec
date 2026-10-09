# services/api/src/cli/create_admin.py
# ============================================================
# Creează (sau actualizează) un cont de administrator.
# ============================================================
# Folosire (din containerul API):
#   docker compose exec api python -m src.cli.create_admin --username admin --email admin@firma.ro
#       → parola e cerută interactiv (necesită TTY: `docker compose exec` fără -T)
#
#   MEETREC_ADMIN_PASSWORD='...' docker compose exec -T -e MEETREC_ADMIN_PASSWORD api \
#       python -m src.cli.create_admin --username admin --email admin@firma.ro --update-existing
#       → non-interactiv (folosit de installer)
#
# Parola NU se transmite niciodată ca argument (ar apărea în `ps` și în istoricul shell-ului).
#
# --update-existing: dacă username-ul există (ex. contul "admin" creat de init.sql),
#   îi setează parola nouă, rolul admin și îl reactivează — elimină parola implicită.
# --disable-default-operator: dezactivează contul "operator" creat de init.sql
#   dacă are încă parola implicită.
# ============================================================

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select

from src.database import engine, session_factory
from src.middleware.auth import hash_password, verify_password
from src.models.audit_log import User, UserRole

# Parola contului "operator" din database/init.sql (seed) — doar pentru a detecta că n-a fost schimbată
_DEFAULT_OPERATOR_PASSWORDS = ("operator123",)
MIN_PASSWORD_LENGTH = 8


def _read_password() -> str:
    password = os.environ.get("MEETREC_ADMIN_PASSWORD")
    if password:
        return password
    if not sys.stdin.isatty():
        sys.exit("EROARE: setează MEETREC_ADMIN_PASSWORD sau rulează interactiv (docker compose exec fără -T).")
    password = getpass.getpass("Parolă: ")
    if password != getpass.getpass("Confirmă parola: "):
        sys.exit("EROARE: parolele nu coincid.")
    return password


async def _run(args: argparse.Namespace, password: str) -> int:
    async with session_factory() as db:
        result = await db.execute(select(User).where(User.username == args.username))
        user = result.scalar_one_or_none()

        if user and not args.update_existing:
            print(f"EROARE: utilizatorul '{args.username}' există deja (folosește --update-existing).", file=sys.stderr)
            return 1

        if user:
            user.password_hash = hash_password(password)
            user.role = UserRole.ADMIN.value
            user.is_active = True
            user.must_change_password = args.must_change_password
            if args.email:
                user.email = args.email.strip().lower()
            if args.full_name:
                user.full_name = args.full_name
            action = "actualizat"
        else:
            if not args.email:
                print("EROARE: --email este obligatoriu pentru un cont nou.", file=sys.stderr)
                return 1
            db.add(User(
                username=args.username,
                email=args.email.strip().lower(),
                full_name=args.full_name,
                password_hash=hash_password(password),
                role=UserRole.ADMIN.value,
                is_active=True,
                must_change_password=args.must_change_password,
            ))
            action = "creat"

        if args.disable_default_operator and args.username != "operator":
            op = (await db.execute(select(User).where(User.username == "operator"))).scalar_one_or_none()
            if op and op.is_active and any(verify_password(p, op.password_hash) for p in _DEFAULT_OPERATOR_PASSWORDS):
                op.is_active = False
                print("Contul implicit 'operator' (parolă neschimbată) a fost dezactivat.")

        await db.commit()

    print(f"Administrator '{args.username}' {action}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Creează sau actualizează un administrator MeetRec.")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--email")
    parser.add_argument("--full-name", default=None)
    parser.add_argument("--update-existing", action="store_true",
                        help="Actualizează parola/rolul dacă utilizatorul există deja.")
    parser.add_argument("--must-change-password", action="store_true",
                        help="Obligă schimbarea parolei la primul login.")
    parser.add_argument("--disable-default-operator", action="store_true",
                        help="Dezactivează contul seed 'operator' dacă are încă parola implicită.")
    args = parser.parse_args()

    password = _read_password()
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"EROARE: parola trebuie să aibă minim {MIN_PASSWORD_LENGTH} caractere.", file=sys.stderr)
        return 1

    async def _main() -> int:
        try:
            return await _run(args, password)
        finally:
            await engine.dispose()

    return asyncio.run(_main())


if __name__ == "__main__":
    sys.exit(main())
