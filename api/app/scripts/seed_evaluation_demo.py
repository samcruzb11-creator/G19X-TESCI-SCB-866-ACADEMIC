"""Opt-in local evaluation seed. Credentials supplied in an external private Markdown contract."""
import argparse
import hashlib
from io import BytesIO

from sqlalchemy import select, text

from app.scripts.evaluation_credentials import load_credentials
from app.core.config import settings
from app.core.security import hash_password, normalize_email, verify_password
from app.models.entities import (
    Area, Auditoria, DecisionAprobacion, Documento, DocumentoAuditoria,
    EventoAuditoria, Evidencia, Hallazgo, HallazgoEvidencia, RondaAprobacion,
    Usuario, VersionDocumento,
)
from app.services.file_transaction import commit_stored_file, discard_uncommitted_file
from app.services.storage_service import StorageService

# Only synthetic roles/names are public; identities and passwords are external.
AREA_CODE = 'EVAL-DEMO'
DATASET_MARKER = 'SEED_EVALUATION_DATASET'
DEMO_BYTES = b'Evidencia sintetica de evaluacion local. No contiene datos reales.\n'


class DemoConflict(RuntimeError):
    """Fixed message only; identities, hashes and driver details stay private."""


def validate_target():
    if settings.app_env != 'development' or settings.db_host not in {'127.0.0.1', 'localhost', '::1'}:
        raise DemoConflict('El seed exige APP_ENV=development y MySQL loopback. Sin cambios.')


def dataset(db, users, area, storage):
    """Create a small synthetic fixture in the caller's transaction, once only."""
    if db.scalar(select(EventoAuditoria.id).where(
            EventoAuditoria.accion == DATASET_MARKER,
            EventoAuditoria.entidad_tipo == 'EVALUACION', EventoAuditoria.entidad_id == 'v1')):
        return None
    for model, codes in ((Auditoria, ('EVAL-AUD-2026', 'EVAL-AUD-PRIVADA')),
                         (Documento, ('EVAL-DOC-2026', 'EVAL-DOC-PRIVADO'))):
        if db.scalar(select(model.id).where(model.codigo.in_(codes)).limit(1)):
            raise DemoConflict('Conflicto con un codigo demo existente. Sin sobrescritura.')
    admin, owner, auditor, approver = users
    audit = Auditoria(codigo='EVAL-AUD-2026', nombre='Auditoría Demo 2026',
        alcance='Expediente sintético para evaluación local.', responsable_id=auditor.id,
        created_by_id=admin.id, estado='PLANNED')
    hidden_audit = Auditoria(codigo='EVAL-AUD-PRIVADA', nombre='Auditoría Demo de alcance restringido',
        alcance='Recurso sintético inaccesible para RESPONSABLE_AREA.', responsable_id=auditor.id,
        created_by_id=admin.id, estado='PLANNED')
    doc = Documento(codigo='EVAL-DOC-2026', titulo='Documento de Evidencia Demo',
        descripcion='Archivo sintético; responsable demo asignado.', tipo='EVIDENCIA',
        estado='DRAFT', area_id=area.id, responsable_id=owner.id, created_by_id=admin.id)
    hidden_doc = Documento(codigo='EVAL-DOC-PRIVADO', titulo='Documento Demo de otro responsable',
        tipo='EVIDENCIA', estado='DRAFT', area_id=area.id, responsable_id=admin.id,
        created_by_id=admin.id)
    db.add_all([audit, hidden_audit, doc, hidden_doc]); db.flush()
    info = storage.save_file(BytesIO(DEMO_BYTES), 'evidencia-demo.txt', 'text/plain')
    try:
        version = VersionDocumento(documento_id=doc.id, numero_version=1,
            storage_key=info.storage_key, nombre_original=info.nombre_original,
            mime_type=info.mime_type, tamano_bytes=info.tamano_bytes, sha256=info.sha256,
            comentario_cambio='Versión sintética inicial de evaluación.', subido_por_id=admin.id)
        db.add(version); db.flush()
        doc.version_vigente_id = version.id
        db.add(DocumentoAuditoria(auditoria_id=audit.id, documento_id=doc.id,
            version_documento_id=version.id, proposito='EVALUACION', asociado_por_id=admin.id))
        evidence = Evidencia(auditoria_id=audit.id, tipo='NOTE', titulo='Evidencia Demo',
            descripcion='Nota sintética para comprobar la relación con un hallazgo.',
            documento_id=doc.id, version_documento_id=version.id, registrada_por_id=admin.id)
        finding = Hallazgo(auditoria_id=audit.id, numero=1, titulo='Hallazgo Demo',
            descripcion='Control documental sintético pendiente de revisión.', categoria='DOCUMENTAL',
            severidad='LOW', estado='OPEN', responsable_id=auditor.id, created_by_id=admin.id)
        round_ = RondaAprobacion(version_documento_id=version.id, numero_ronda=1,
            estado='PENDING', solicitada_por_id=admin.id)
        db.add_all([evidence, finding, round_]); db.flush()
        db.add(HallazgoEvidencia(hallazgo_id=finding.id, evidencia_id=evidence.id,
            vinculada_por_id=admin.id, contexto='Vínculo sintético de evaluación.'))
        db.add(DecisionAprobacion(ronda_aprobacion_id=round_.id, aprobador_id=approver.id, estado='PENDING'))
        for entity, entity_id in (('AUDITORIA', audit.id), ('AUDITORIA', hidden_audit.id),
                ('DOCUMENTO', doc.id), ('DOCUMENTO', hidden_doc.id), ('HALLAZGO', finding.id),
                ('EVIDENCIA', evidence.id), ('RONDA_APROBACION', round_.id), ('EVALUACION', 'v1')):
            db.add(EventoAuditoria(actor_id=admin.id, actor_snapshot='Administrador Demo (ADMIN)',
                accion=DATASET_MARKER, entidad_tipo=entity, entidad_id=str(entity_id),
                datos_nuevos={'origen': 'seed local explícito', 'sintetico': True}))
        db.flush()
        return info.storage_key
    except Exception:
        discard_uncommitted_file(db, storage, info.storage_key)
        raise


def seed(*, factory, credentials_file=None, storage=None, with_dataset=False):
    """Serialize invocations; all inserts are atomic. Never update existing rows."""
    validate_target()
    accounts = load_credentials(credentials_file)
    storage = storage or StorageService()
    with factory() as probe:
        engine = probe.get_bind()
    with engine.connect() as connection:
        name, version = connection.execute(text('SELECT DATABASE(), VERSION()')).one()
        if not name or 'mariadb' in version.lower() or int(version.split('.')[0]) < 8:
            raise DemoConflict('Se requiere MySQL 8 y un schema migrado. Sin cambios.')
        if connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() != '005':
            raise DemoConflict('Ejecute Alembic hasta 005 antes del seed. Sin cambios.')
        lock = 'seed_evaluation:' + hashlib.sha256(name.encode()).hexdigest()[:32]
        acquired = connection.execute(text('SELECT GET_LOCK(:name, 5)'), {'name': lock}).scalar_one() == 1
        connection.rollback()
        if not acquired:
            raise DemoConflict('Otro seed está en curso. Sin cambios.')
        try:
            with factory(bind=connection) as db:
                users, created, key = [], 0, None
                try:
                    for account in accounts:
                        email, role, display, password = account.email, account.role, account.name, account.password
                        row = db.scalar(select(Usuario).where(Usuario.correo_normalizado == normalize_email(email)))
                        if row is not None:
                            if (row.correo != email or row.nombre != display or row.rol != role
                                    or not row.activo or not verify_password(password, row.password_hash)):
                                raise DemoConflict('Conflicto con una cuenta demo existente. No se modifica ninguna cuenta.')
                        else:
                            row = Usuario(correo=email, correo_normalizado=normalize_email(email), nombre=display,
                                          rol=role, activo=True, password_hash=hash_password(password))
                            db.add(row); created += 1
                        users.append(row)
                    area = db.scalar(select(Area).where(Area.codigo == AREA_CODE))
                    if area is not None and (area.nombre != 'Área Demo' or not area.activa):
                        raise DemoConflict('Conflicto con el area demo existente. Sin cambios.')
                    if area is None:
                        area = Area(codigo=AREA_CODE, nombre='Área Demo', activa=True)
                        db.add(area)
                    db.flush()
                    if with_dataset:
                        key = dataset(db, users, area, storage)
                    db.flush()
                except Exception:
                    if key is not None:
                        discard_uncommitted_file(db, storage, key)
                    else:
                        db.rollback()
                    raise
                if key is not None:
                    commit_stored_file(db, storage, key)
                else:
                    db.commit()
                return created
        finally:
            connection.rollback()
            if connection.execute(text('SELECT RELEASE_LOCK(:name)'), {'name': lock}).scalar_one() != 1:
                connection.invalidate()
            else:
                connection.rollback()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Cuentas DEMO exclusivas de evaluación local; nunca producción')
    parser.add_argument('--confirm-local-demo', action='store_true', help='Autoriza sólo inserciones demo explícitas')
    parser.add_argument('--credentials-file', help='Documento privado externo de TODO Academy')
    parser.add_argument('--with-dataset', action='store_true', help='Añade expediente sintético pequeño una sola vez')
    args = parser.parse_args(argv)
    print('Plan: 4 cuentas demo (ADMIN, RESPONSABLE_AREA, AUDITOR_INTERNO, APROBADOR) y Área Demo.')
    if args.with_dataset:
        print('Dataset: 2 auditorías, 2 documentos, 1 versión/archivo TXT, 1 nota, 1 hallazgo, 1 ronda y 1 decisión pendiente.')
    print('No se actualizan ni eliminan registros existentes. Sólo evaluación local.')
    if not args.confirm_local_demo:
        print('Sin cambios. Para ejecutar, añada --confirm-local-demo.')
        return 0
    try:
        validate_target()
        from app.db.session import SessionLocal
        count = seed(factory=SessionLocal, credentials_file=args.credentials_file, with_dataset=args.with_dataset)
        print(f'Seed verificado. Cuentas nuevas: {count}. Use exclusivamente el documento privado externo.')
        return 0
    except Exception:
        print('Seed no completado: revise archivo privado externo, entorno local, migración 005 o conflicto de identidad. No sobrescriba datos.')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
