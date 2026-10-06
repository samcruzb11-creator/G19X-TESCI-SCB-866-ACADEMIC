"""Interactive, local-only bootstrap of the first active administrator."""
import argparse
from getpass import getpass, GetPassWarning
import hashlib
import ipaddress
from pathlib import Path
import socket
import sys
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password, normalize_email
from app.models.entities import Usuario
from app.schemas.account_access import valid_address


class BootstrapError(Exception):
    """Only fixed, safe messages may cross the CLI boundary."""


def validate_identity(nombre, correo):
    nombre = nombre.strip()
    if not 2 <= len(nombre) <= 160 or any(ord(c) < 32 or ord(c) == 127 for c in nombre):
        raise BootstrapError("Nombre invalido: use entre 2 y 160 caracteres sin controles.")
    try:
        correo = valid_address(correo)
    except (ValueError, TypeError):
        raise BootstrapError("Formato de correo invalido.") from None
    return nombre, correo


def active_admin_exists(db, *, locking=False):
    query = select(Usuario.id).where(Usuario.rol == "ADMIN", Usuario.activo.is_(True)).limit(1)
    if locking:
        query = query.with_for_update()
    return db.scalar(query) is not None


def create_first_admin(nombre, correo, password, *, factory):
    """One user transaction; serialize bootstrap on a connection-owned MySQL lock.

    The caller must supply its guarded session factory. No session/token/mail or
    existing-user update is performed. MySQL decides address equivalence.
    """
    nombre, correo = validate_identity(nombre, correo)
    try:
        hashed = hash_password(password)
    except ValueError:
        raise BootstrapError("La contrasena debe tener entre 12 y 1024 caracteres.") from None
    del password
    with factory() as probe:
        engine = probe.get_bind()
    with engine.connect() as connection:
        database, version = connection.execute(text("SELECT DATABASE(), VERSION()")).one()
        if not database or "mariadb" in version.lower() or int(version.split(".")[0]) < 8:
            raise BootstrapError("Se requiere un schema existente en MySQL 8 o superior.")
        lock_name = "bootstrap_admin:" + hashlib.sha256(database.encode()).hexdigest()[:32]
        acquired = False
        try:
            acquired = connection.execute(text("SELECT GET_LOCK(:name, 5)"), {"name": lock_name}).scalar_one() == 1
            connection.rollback()  # GET_LOCK is connection-owned, not transactional.
            if not acquired:
                raise BootstrapError("Otro bootstrap esta en curso. Sin cambios.")
            with factory(bind=connection) as db:
                try:
                    with db.begin():
                        if active_admin_exists(db, locking=True):
                            raise BootstrapError("Ya existe un ADMIN activo. Bootstrap deshabilitado.")
                        if db.scalar(select(Usuario.id).where(Usuario.correo_normalizado == normalize_email(correo))) is not None:
                            raise BootstrapError("El correo ya pertenece a un usuario. Sin cambios.")
                        user = Usuario(nombre=nombre, correo=correo,
                            correo_normalizado=normalize_email(correo), password_hash=hashed,
                            rol="ADMIN", activo=True)
                        db.add(user)
                        db.flush()
                        if user.rol != "ADMIN" or not user.activo or not user.password_hash.startswith("$argon2id$"):
                            raise BootstrapError("No se pudo validar el nuevo administrador.")
                        user_id = user.id
                    return user_id
                except IntegrityError:
                    db.rollback()
                    raise BootstrapError("No se pudo crear el ADMIN: identidad no disponible. Sin cambios.") from None
        finally:
            connection.rollback()
            if acquired:
                released = connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name}).scalar_one()
                connection.rollback()
                if released != 1:
                    connection.invalidate()


def validate_local_target(factory):
    from app.core.config import settings
    if (settings.db_host not in {"127.0.0.1", "localhost", "::1"}
        or settings.db_port != 3306 or settings.db_name != "sistema_trazabilidad"
        or settings.app_env != "development"):
        raise BootstrapError("Bootstrap autorizado solo para sistema_trazabilidad local en development.")
    if not all(ipaddress.ip_address(item[4][0]).is_loopback
               for item in socket.getaddrinfo(settings.db_host, settings.db_port)):
        raise BootstrapError("La conexion configurada no resuelve a loopback.")
    with factory() as db:
        database, version, port = db.execute(text("SELECT DATABASE(), VERSION(), @@port")).one()
        if (database != "sistema_trazabilidad" or port != 3306
            or "mariadb" in version.lower() or int(version.split(".")[0]) < 8
            or db.execute(text("SELECT version_num FROM alembic_version")).scalars().all() != ["004"]):
            raise BootstrapError("La BD local no coincide con MySQL 8 y Alembic 004. Sin cambios.")
        if active_admin_exists(db):
            raise BootstrapError("Ya existe un ADMIN activo. Bootstrap deshabilitado.")


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # Unknown arguments might contain a password. Never echo them.
        self.exit(2, "Esta CLI no acepta datos por argumentos; use los prompts interactivos.\n")


def main(argv=None):
    SafeParser(description="Crear exclusivamente el primer ADMIN local; entrada interactiva.").parse_args(argv)
    from app.db.session import SessionLocal
    try:
        validate_local_target(SessionLocal)
        nombre = input("Nombre del primer ADMIN: ")
        correo = input("Correo del primer ADMIN: ")
        nombre, correo = validate_identity(nombre, correo)
        with warnings.catch_warnings():
            warnings.simplefilter("error", GetPassWarning)
            password = getpass("Contrasena (12-1024 caracteres; entrada oculta): ")
            confirmation = getpass("Repita la contrasena: ")
        if password != confirmation:
            raise BootstrapError("Las contrasenas no coinciden. Sin cambios.")
        del confirmation
        if input("Escriba CREAR ADMIN LOCAL para confirmar: ") != "CREAR ADMIN LOCAL":
            print("Cancelado. Sin cambios.")
            return 1
        user_id = create_first_admin(nombre, correo, password, factory=SessionLocal)
        del password
        print(f"Primer ADMIN activo creado: usuario-id {user_id}. Sin autologin.")
        return 0
    except BootstrapError as exc:
        print(str(exc))
        return 1
    except (EOFError, KeyboardInterrupt, GetPassWarning):
        print("Entrada segura no completada. Sin cambios confirmados.")
        return 1
    except Exception:
        # Commit acknowledgement may be ambiguous. Never retry automatically or
        # print driver/SQL inputs containing a password hash or connection data.
        print("No fue posible confirmar el bootstrap. Inspeccione el estado antes de repetir.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
