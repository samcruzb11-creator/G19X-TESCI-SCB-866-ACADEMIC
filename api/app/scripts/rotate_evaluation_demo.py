"""Guarded explicit rotation; preserves actors, records, files and historical events."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re

from sqlalchemy import inspect, select, text, update

from app.core.security import hash_password, normalize_email, verify_password
from app.models.entities import Usuario, EventoAuditoria, Documento, Auditoria, DecisionAprobacion
from app.models.auth import AuthSession
from app.models.account_access import AuthActionToken
from app.scripts.evaluation_credentials import load_credentials
from app.scripts.seed_evaluation_demo import DemoConflict, DATASET_MARKER, validate_target


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str,
                                    ensure_ascii=False).encode('utf-8')).hexdigest()


def snapshot(connection):
    """Fingerprint every table, DDL and row, without returning raw values in CLI output."""
    inspector = inspect(connection)
    result = {}
    quote = connection.dialect.identifier_preparer.quote
    for table in sorted(inspector.get_table_names()):
        pk = inspector.get_pk_constraint(table)['constrained_columns']
        order = ' ORDER BY ' + ','.join(quote(c) for c in pk) if pk else ''
        rows = [tuple(row) for row in connection.exec_driver_sql('SELECT * FROM ' + quote(table) + order)]
        ddl = connection.exec_driver_sql('SHOW CREATE TABLE ' + quote(table)).one()[1]
        result[table] = digest([ddl, rows])
    return result


@contextmanager
def locked_database(factory):
    validate_target()
    with factory() as probe:
        engine = probe.get_bind()
    with engine.connect() as connection:
        name, version = connection.execute(text('SELECT DATABASE(), VERSION()')).one()
        if not name or 'mariadb' in version.lower() or int(version.split('.')[0]) < 8:
            raise DemoConflict('Se requiere MySQL 8 local.')
        if connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() != '005':
            raise DemoConflict('Se requiere Alembic 005.')
        lock = 'seed_evaluation:' + hashlib.sha256(name.encode()).hexdigest()[:32]
        acquired = connection.execute(text('SELECT GET_LOCK(:name, 5)'), {'name': lock}).scalar_one() == 1
        connection.rollback()
        if not acquired:
            raise DemoConflict('Otra operación demo está en curso.')
        try:
            with factory(bind=connection) as db:
                yield db
        finally:
            connection.rollback()
            if connection.execute(text('SELECT RELEASE_LOCK(:name)'), {'name': lock}).scalar_one() != 1:
                connection.invalidate()
            else:
                connection.rollback()


def validate_demo_identity(db, accounts, expected_ids):
    if (len(expected_ids) != 4 or len(set(expected_ids)) != 4
            or any(type(i) is not int or i <= 2 for i in expected_ids)):
        raise DemoConflict('Se requieren cuatro IDs demo explícitos; IDs históricos protegidos.')
    users = []
    for account, identity in zip(accounts, expected_ids):
        row = db.scalar(select(Usuario).where(Usuario.id == identity).with_for_update())
        if (row is None or row.correo != account.email
                or row.correo_normalizado != normalize_email(account.email)
                or row.nombre != account.name or row.rol != account.role or not row.activo
                or not verify_password(account.password, row.password_hash)):
            raise DemoConflict('La identidad previa no coincide exactamente. Sin cambios.')
        users.append(row)
    admin, owner, auditor, approver = users
    marker = db.scalar(select(EventoAuditoria).where(
        EventoAuditoria.accion == DATASET_MARKER, EventoAuditoria.entidad_tipo == 'EVALUACION',
        EventoAuditoria.entidad_id == 'v1', EventoAuditoria.actor_id == admin.id))
    doc = db.scalar(select(Documento).where(Documento.codigo == 'EVAL-DOC-2026',
        Documento.created_by_id == admin.id, Documento.responsable_id == owner.id))
    audit = db.scalar(select(Auditoria).where(Auditoria.codigo == 'EVAL-AUD-2026',
        Auditoria.created_by_id == admin.id, Auditoria.responsable_id == auditor.id))
    decision = db.scalar(select(DecisionAprobacion.id).where(DecisionAprobacion.aprobador_id == approver.id))
    if marker is None or doc is None or audit is None or decision is None:
        raise DemoConflict('No se acredita la procedencia del dataset demo para los cuatro actores.')
    return users


def protected_rows(db, ids):
    """Includes all non-demo users, historical ID 1, unrelated sessions and FK counts."""
    connection = db.connection()
    quote = connection.dialect.identifier_preparer.quote
    result = {}
    for table, actor, order in [('usuarios', 'id', 'id'), ('auth_sessions', 'usuario_id', 'sid'),
                                ('auth_action_tokens', 'usuario_id', 'token_hash')]:
        result[table] = [tuple(r) for r in connection.execute(text(
            'SELECT * FROM ' + quote(table) + ' WHERE ' + quote(actor)
            + ' IS NULL OR ' + quote(actor) + ' NOT IN (:a,:b,:c,:d) ORDER BY ' + quote(order)),
            dict(zip(('a', 'b', 'c', 'd'), ids)))]
    result['actors'] = [tuple(r) for r in connection.execute(text(
        'SELECT id,nombre,rol,activo,created_at FROM usuarios WHERE id IN (:a,:b,:c,:d) ORDER BY id'),
        dict(zip(('a', 'b', 'c', 'd'), ids)))]
    inspector = inspect(connection)
    for table in inspector.get_table_names():
        for fk in inspector.get_foreign_keys(table):
            if fk['referred_table'] == 'usuarios':
                for column in fk['constrained_columns']:
                    result[table + '.' + column] = [tuple(r) for r in connection.exec_driver_sql(
                        'SELECT ' + quote(column) + ', COUNT(*) FROM ' + quote(table)
                        + ' GROUP BY ' + quote(column) + ' ORDER BY ' + quote(column))]
    return result


def rotate(*, factory, credentials_file, previous_credentials_file, expected_ids,
           expected_fingerprint=None, confirm=False):
    validate_target()
    previous = load_credentials(previous_credentials_file, allow_legacy=True)
    target = load_credentials(credentials_file)
    if any(a.password in {p.password for p in previous} for a in target):
        raise DemoConflict('La rotación exige contraseñas nuevas para todos los roles.')
    with locked_database(factory) as db:
        users = validate_demo_identity(db, previous, expected_ids)
        preserved = protected_rows(db, expected_ids)
        before = snapshot(db.connection())
        fingerprint = digest(before)
        if not confirm:
            db.rollback()
            return {'plan': True, 'ids': expected_ids, 'fingerprint': fingerprint}
        if (not isinstance(expected_fingerprint, str)
                or not re.fullmatch('[0-9a-f]{64}', expected_fingerprint)
                or fingerprint != expected_fingerprint):
            raise DemoConflict('Fingerprint previo ausente o cambiado. Obtenga un plan nuevo.')
        for account in target:
            collision = db.scalar(select(Usuario.id).where(
                Usuario.correo_normalizado == normalize_email(account.email)))
            if collision is not None and collision not in expected_ids:
                raise DemoConflict('Identificador destino ocupado. Sin cambios.')
            # Avoid cross-role swaps and unique-index intermediate conflicts.
            if any(account.email == old.email and account.role != old.role for old in previous):
                raise DemoConflict('No se permiten intercambios de identidad entre actores.')
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for row, account in zip(users, target):
            row.correo = account.email
            row.correo_normalizado = normalize_email(account.email)
            row.password_hash = hash_password(account.password)
        sessions = db.execute(update(AuthSession).where(AuthSession.usuario_id.in_(expected_ids),
            AuthSession.revoked_at.is_(None)).values(revoked_at=now)).rowcount
        tokens = db.execute(update(AuthActionToken).where(AuthActionToken.usuario_id.in_(expected_ids),
            AuthActionToken.consumed_at.is_(None)).values(consumed_at=now)).rowcount
        db.flush()
        after = snapshot(db.connection())
        allowed = {'usuarios', 'auth_sessions', 'auth_action_tokens'}
        if any(before[t] != after[t] for t in before if t not in allowed):
            raise DemoConflict('Cambios inesperados fuera de credenciales/sesiones. Transacción rechazada.')
        if protected_rows(db, expected_ids) != preserved:
            raise DemoConflict('Cambios inesperados de actores históricos, relaciones o sesiones ajenas.')
        db.commit()
        return {'plan': False, 'ids': expected_ids, 'sessions_revoked': sessions,
                'tokens_invalidated': tokens, 'password_hashes_changed': 4,
                'fingerprint_before': fingerprint, 'fingerprint_after': digest(after),
                'historical_events_preserved': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Rotación separada y transaccional de actores demo verificados')
    parser.add_argument('--credentials-file', required=True)
    parser.add_argument('--previous-credentials-file', required=True)
    parser.add_argument('--demo-user-ids', required=True, help='IDs en orden ADMIN, RESPONSABLE_AREA, AUDITOR_INTERNO, APROBADOR')
    parser.add_argument('--expected-fingerprint')
    parser.add_argument('--confirm-rotate-demo', action='store_true')
    args = parser.parse_args(argv)
    try:
        ids = [int(i) for i in args.demo_user_ids.split(',')]
        from app.db.session import SessionLocal
        result = rotate(factory=SessionLocal, credentials_file=args.credentials_file,
            previous_credentials_file=args.previous_credentials_file, expected_ids=ids,
            expected_fingerprint=args.expected_fingerprint, confirm=args.confirm_rotate_demo)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception:
        print('Rotación no confirmada: revise entorno, contrato externo, IDs, procedencia y fingerprint. Verifique estado antes de reintentar.')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
