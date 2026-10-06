"""Scoped findings, serialized with 7A's parent audit lock. No storage reimplementation."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import logging
from fastapi import HTTPException
from sqlalchemy import select, func, exists
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import joinedload
from app.models.entities import Auditoria, Hallazgo, HallazgoEvidencia, Evidencia, Usuario, EventoAuditoria
from app.schemas.hallazgo import HallazgoRead
from app.schemas.auditoria import naive_utc
from app.services import authorization_service as authz
from app.services.documento_service import _log_evento

TRANSITIONS = {'OPEN': {'IN_PROGRESS', 'ACCEPTED_RISK'},
    'IN_PROGRESS': {'PENDING_VERIFICATION', 'ACCEPTED_RISK'},
    'PENDING_VERIFICATION': {'IN_PROGRESS', 'CLOSED', 'ACCEPTED_RISK'},
    'CLOSED': set(), 'ACCEPTED_RISK': set()}
BUSINESS = ('auditoria_id', 'numero', 'titulo', 'descripcion', 'categoria', 'severidad', 'estado',
    'responsable_id', 'fecha_limite', 'resolucion', 'cerrado_por_id', 'cerrado_en', 'created_by_id', 'updated_by_id')


def snapshot(row):
    return {name: value.isoformat() if hasattr(value, 'isoformat') else value
            for name in BUSINESS for value in [getattr(row, name)]}


def log(db, user, row, action, old=None, data=None):
    _log_evento(db, actor=user, accion=action, entidad_tipo='HALLAZGO', entidad_id=row.id,
        correlation_id=str(uuid4()), datos_anteriores=old,
        datos_nuevos={**(data if data is not None else snapshot(row)), 'resultado': 'SUCCESS'})


def transaction(db, operation):
    try:
        result = operation()
        db.flush()
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Conflicto de integridad; recargue antes de continuar') from None
    except Exception as exc:
        db.rollback()
        logging.getLogger(__name__).error('Finding mutation failed: %s', type(exc).__name__)
        raise HTTPException(503 if isinstance(exc, SQLAlchemyError) else 500,
            'No fue posible confirmar la operacion; consulte antes de repetir') from None


def resource(db, user, finding_id, action='hallazgo.read'):
    return authz.resource(db, user, Hallazgo, finding_id, action, authz.hallazgo_scope)


def lock_audit(db, user, audit_id, action):
    authz.require_permission(user, action)
    row = db.scalar(select(Auditoria).where(Auditoria.id == audit_id,
        authz.auditoria_scope(user)).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404, 'Recurso no encontrado')
    if row.estado not in {'IN_PROGRESS', 'IN_REVIEW'}:
        raise HTTPException(409, 'Los hallazgos requieren una auditoria activa o en revision')
    return row


def lock_finding(db, user, finding_id, action='hallazgo.link'):
    initial = resource(db, user, finding_id, action)
    lock_audit(db, user, initial.auditoria_id, action)
    row = db.scalar(select(Hallazgo).where(Hallazgo.id == finding_id,
        authz.hallazgo_scope(user)).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404, 'Recurso no encontrado')
    if row.estado in {'CLOSED', 'ACCEPTED_RISK'}:
        raise HTTPException(409, 'El hallazgo es terminal')
    return row


def fresh(row, expected):
    if row.updated_at != naive_utc(expected):
        raise HTTPException(409, 'El hallazgo cambio; recargue antes de continuar')


def touch(row, user):
    # Ensure tokens advance even when two writes fit in one clock tick.
    row.updated_at = max(datetime.now(timezone.utc).replace(tzinfo=None), row.updated_at + timedelta(microseconds=1))
    row.updated_by_id = user.id


def responsible(db, user, value):
    if user.rol != 'ADMIN' and value is not None and value != user.id:
        raise HTTPException(403, 'Reasignacion reservada a ADMIN')
    if value is not None and db.scalar(select(Usuario.id).where(Usuario.id == value,
        authz.eligible_users_scope()).with_for_update()) is None:
        raise HTTPException(404, 'Recurso no encontrado')


def visible_links(user):
    return (HallazgoEvidencia.evidencia_id == Evidencia.id,
        Evidencia.auditoria_id == Hallazgo.auditoria_id,
        authz.evidencia_scope(user), authz.evidence_consistency())


def read_query(user):
    count = select(func.count()).select_from(HallazgoEvidencia).join(Evidencia,
        HallazgoEvidencia.evidencia_id == Evidencia.id).where(
        HallazgoEvidencia.hallazgo_id == Hallazgo.id, *visible_links(user)).correlate(Hallazgo).scalar_subquery()
    return select(Hallazgo, count.label('evidencias_count')).where(authz.hallazgo_scope(user)).options(joinedload(Hallazgo.responsable))


def serialize(result):
    row, count = result
    return HallazgoRead.model_validate(row).model_copy(update={'evidencias_count': count})


def detail(db, user, finding_id):
    authz.require_permission(user, 'hallazgo.read')
    result = db.execute(read_query(user).where(Hallazgo.id == finding_id)).first()
    if result is None:
        raise HTTPException(404, 'Recurso no encontrado')
    return serialize(result)


def list_findings(db, user, filters):
    authz.require_permission(user, 'hallazgo.read')
    stmt = read_query(user)
    for name in ('auditoria_id', 'estado', 'severidad', 'responsable_id'):
        value = getattr(filters, name)
        if value is not None:
            stmt = stmt.where(getattr(Hallazgo, name) == value)
    if filters.evidencia_id is not None:
        authz.resource(db, user, Evidencia, filters.evidencia_id, 'evidencia.read', authz.evidencia_scope)
        stmt = stmt.where(exists(select(HallazgoEvidencia.hallazgo_id).join(Evidencia,
            HallazgoEvidencia.evidencia_id == Evidencia.id).where(
            HallazgoEvidencia.hallazgo_id == Hallazgo.id,
            Evidencia.id == filters.evidencia_id, *visible_links(user)).correlate(Hallazgo)))
    if filters.q:
        term = filters.q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        stmt = stmt.where(Hallazgo.titulo.ilike('%'+term+'%', escape='\\') |
            Hallazgo.descripcion.ilike('%'+term+'%', escape='\\'))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    column = Hallazgo.numero if 'numero' in filters.orden else Hallazgo.id
    order = column.desc() if filters.orden.startswith('-') else column.asc()
    return [serialize(row) for row in db.execute(stmt.order_by(order, Hallazgo.id).limit(filters.limit).offset(filters.offset)).unique()], total


def create(db, user, payload):
    def operation():
        lock_audit(db, user, payload.auditoria_id, 'hallazgo.create')
        responsible(db, user, payload.responsable_id)
        # Current locking read avoids a stale REPEATABLE READ snapshot after waiting.
        last = db.scalar(select(Hallazgo.numero).where(Hallazgo.auditoria_id == payload.auditoria_id)
            .order_by(Hallazgo.numero.desc()).limit(1).with_for_update())
        row = Hallazgo(**payload.model_dump(), numero=(last or 0)+1, estado='OPEN', created_by_id=user.id)
        db.add(row)
        db.flush()
        log(db, user, row, 'CREACION_HALLAZGO')
        return row.id
    return detail(db, user, transaction(db, operation))


def edit(db, user, finding_id, payload):
    def operation():
        row = lock_finding(db, user, finding_id, 'hallazgo.update')
        fresh(row, payload.updated_at_esperado)
        old = snapshot(row)
        if 'responsable_id' in payload.model_fields_set:
            responsible(db, user, payload.responsable_id)
        for name, value in payload.model_dump(exclude_unset=True, exclude={'updated_at_esperado'}).items():
            setattr(row, name, value)
        if snapshot(row) == old:
            raise HTTPException(409, 'No hay cambios de negocio')
        touch(row, user)
        log(db, user, row, 'ACTUALIZACION_HALLAZGO', old)
        return row.id
    return detail(db, user, transaction(db, operation))


def transition(db, user, finding_id, payload):
    def operation():
        row = lock_finding(db, user, finding_id, 'hallazgo.transition')
        fresh(row, payload.updated_at_esperado)
        if row.estado != payload.estado_esperado or payload.estado not in TRANSITIONS[row.estado]:
            raise HTTPException(409, 'Transicion de estado no permitida')
        if payload.estado == 'ACCEPTED_RISK' and user.rol != 'ADMIN':
            raise HTTPException(403, 'Aceptacion de riesgo reservada a ADMIN')
        old = snapshot(row)
        if payload.resolucion is not None:
            row.resolucion = payload.resolucion
        if payload.estado in {'CLOSED', 'ACCEPTED_RISK'}:
            if not row.resolucion or not row.resolucion.strip():
                raise HTTPException(422, 'Debe registrar una resolucion')
            row.cerrado_por_id = user.id
            row.cerrado_en = datetime.now(timezone.utc).replace(tzinfo=None)
        row.estado = payload.estado
        touch(row, user)
        log(db, user, row, 'CAMBIO_ESTADO_HALLAZGO', old)
        return row.id
    return detail(db, user, transaction(db, operation))


def prepare_new_evidence(db, user, finding_id, audit_id):
    if finding_id is None:
        return None
    initial = resource(db, user, finding_id, 'hallazgo.link')
    if initial.auditoria_id != audit_id:
        raise HTTPException(404, 'Recurso no encontrado')
    return lock_finding(db, user, finding_id)


def attach_new(db, user, row, evidence, contexto=None):
    """Caller holds audit/finding locks; link and event share evidence's commit."""
    db.add(HallazgoEvidencia(hallazgo_id=row.id, evidencia_id=evidence.id,
        vinculada_por_id=user.id, contexto=contexto))
    touch(row, user)
    log(db, user, row, 'ASOCIACION_EVIDENCIA_HALLAZGO', data={
        'auditoria_id': row.auditoria_id, 'evidencia_id': evidence.id, 'contexto': contexto})


def associate(db, user, finding_id, payload):
    def operation():
        row = lock_finding(db, user, finding_id)
        evidence = db.scalar(select(Evidencia).where(Evidencia.id == payload.evidencia_id,
            Evidencia.auditoria_id == row.auditoria_id, authz.evidencia_scope(user),
            authz.evidence_consistency()).with_for_update().execution_options(populate_existing=True))
        if evidence is None:
            raise HTTPException(404, 'Recurso no encontrado')
        if evidence.tipo == 'FILE':
            from app.services.evidencia_service import evidencia_service
            try:
                available = bool(evidence.storage_key) and evidencia_service.storage.get_absolute_path(evidence.storage_key).is_file()
            except (ValueError, OSError):
                available = False
            if not available:
                raise HTTPException(404, 'Recurso no encontrado')
        duplicate = db.scalar(select(HallazgoEvidencia).where(
            HallazgoEvidencia.hallazgo_id == finding_id,
            HallazgoEvidencia.evidencia_id == evidence.id).with_for_update())
        if duplicate is not None:
            raise HTTPException(409, 'La evidencia ya esta asociada')
        attach_new(db, user, row, evidence, payload.contexto)
        return row.id
    return detail(db, user, transaction(db, operation))


def evidence_list(db, user, finding_id, page):
    resource(db, user, finding_id)
    stmt = select(Evidencia).join(HallazgoEvidencia, HallazgoEvidencia.evidencia_id == Evidencia.id).join(
        Hallazgo, Hallazgo.id == HallazgoEvidencia.hallazgo_id).where(
        Hallazgo.id == finding_id, authz.hallazgo_scope(user), *visible_links(user))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list(db.scalars(stmt.order_by(Evidencia.id).limit(page.limit).offset(page.offset)))
    return rows, total


def history(db, user, finding_id, page):
    resource(db, user, finding_id, 'hallazgo.history')
    stmt = select(EventoAuditoria).where(EventoAuditoria.entidad_tipo == 'HALLAZGO',
        EventoAuditoria.entidad_id == str(finding_id))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    def safe(data):
        return {k: v for k, v in data.items() if k in BUSINESS or k in {'evidencia_id', 'contexto', 'resultado'}} if data else None
    return [dict(id=row.id, actor_id=row.actor_id, accion=row.accion, ocurrido_en=row.ocurrido_en,
        datos_anteriores=safe(row.datos_anteriores), datos_nuevos=safe(row.datos_nuevos))
        for row in db.scalars(stmt.order_by(EventoAuditoria.ocurrido_en.desc(), EventoAuditoria.id.desc())
            .limit(page.limit).offset(page.offset))], total
