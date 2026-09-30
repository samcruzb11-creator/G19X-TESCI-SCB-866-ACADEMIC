"""Explicit password update for exactly one existing user; never creates users."""
import argparse
from getpass import getpass, GetPassWarning
from pathlib import Path
import sys
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Establecer contraseña de un usuario existente")
    parser.add_argument("--usuario-id", type=int, required=True)
    parser.add_argument("--correo", required=True, help="Confirmación de identidad del usuario seleccionado")
    args = parser.parse_args()
    if args.usuario_id <= 0:
        parser.error("usuario-id debe ser positivo")
    from app.core.security import hash_password, normalize_email
    from app.db.session import SessionLocal
    from app.models.entities import Usuario
    from app.models.auth import AuthSession
    from sqlalchemy import select, update
    from datetime import datetime, timezone

    try:
        # getpass otherwise falls back to visible input on unsupported terminals.
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            password = getpass("Nueva contraseña (mínimo 12 caracteres): ")
            confirmation = getpass("Repita la contraseña: ")
        if password != confirmation:
            print("Las contraseñas no coinciden. Sin cambios.")
            return 1
        try:
            hashed = hash_password(password)
        except ValueError:
            print("La contraseña debe tener entre 12 y 1024 caracteres. Sin cambios.")
            return 1
        del password, confirmation
        if input(f"Escriba CAMBIAR {args.usuario_id} para confirmar: ") != f"CAMBIAR {args.usuario_id}":
            print("Cancelado. Sin cambios.")
            return 1
        with SessionLocal() as db:
            user = db.scalar(select(Usuario).where(Usuario.id == args.usuario_id).with_for_update())
            if user is None or user.correo_normalizado != normalize_email(args.correo):
                print("La identidad seleccionada no coincide. Sin cambios.")
                return 1
            user.password_hash = hashed
            # Password changes invalidate only this user's existing sessions.
            db.execute(update(AuthSession).where(AuthSession.usuario_id == user.id,
                                                AuthSession.revoked_at.is_(None)).values(
                revoked_at=datetime.now(timezone.utc).replace(tzinfo=None)))
            db.commit()
        print("Contraseña actualizada; sesiones anteriores revocadas.")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("Cancelado. Sin cambios confirmados.")
        return 1
    except Exception:
        # Driver exceptions may contain credentials; do not print them.
        print("No fue posible confirmar la actualización. Verifique el estado antes de repetir.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
