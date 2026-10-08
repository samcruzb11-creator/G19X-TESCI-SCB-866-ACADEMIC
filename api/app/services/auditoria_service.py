"""Scoped audit lifecycle. A mutation and its event share one transaction."""
from datetime import datetime, timezone
from uuid import uuid4
import logging

from fastapi import HTTPException
from sqlalchemy import select, func, exists
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import joinedload

from app.models.entities import Auditoria, Area, Documento, DocumentoAuditoria, EventoAuditoria
from app.schemas.auditoria import AuditoriaRead, AuditReference, naive_utc
from app.services import authorization_service as authz
from app.services.documento_service import _log_evento

TRANSITIONS = {'PLANNED': {'IN_PROGRESS'}, 'IN_PROGRESS': {'IN_REVIEW'},
               'IN_REVIEW': {'IN_PROGRESS', 'COMPLETED'}, 'COMPLETED': set(), 'CANCELLED': set()}
EVENTS = {('PLANNED', 'IN_PROGRESS'): 'ACTIVACION_AUDITORIA',
          ('IN_PROGRESS', 'IN_REVIEW'): 'REVISION_AUDITORIA',
          ('IN_REVIEW', 'IN_PROGRESS'): 'REACTIVACION_AUDITORIA',
          ('IN_REVIEW', 'COMPLETED'): 'CIERRE_AUDITORIA'}
BUSINESS = ('codigo', 'nombre', 'alcance', 'estado', 'responsable_id', 'fecha_inicio_prevista',
            'fecha_fin_prevista', 'iniciada_en', 'completada_en', 'created_by_id', 'updated_by_id')


def snapshot(row):
    return {name: value.isoformat() if hasattr(value, 'isoformat') else value
            for name in BUSINESS for value in [getattr(row, name)]}


def resource(db, user, audit_id, *, action='auditoria.read', locking=False):
    authz.require_permission(user, action)
    stmt = select(Auditoria).where(Auditoria.id == audit_id, authz.auditoria_scope(user))
    if locking:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    else:
        stmt = stmt.options(joinedload(Auditoria.responsable))
    row = db.scalar(stmt)
    if row is None:
        raise HTTPException(404, 'Recurso no encontrado')
    if locking:
        actor = authz.lock_actor(db, user.id, action)
        if db.scalar(select(Auditoria.id).where(Auditoria.id == audit_id,
                authz.auditoria_scope(actor)).with_for_update()) is None:
            raise HTTPException(404, 'Recurso no encontrado')
    return row


def read_rows(db, rows):
    """One area query for the whole bounded page; never one query per audit."""
    refs = {}
    if rows:
        stmt = select(DocumentoAuditoria.auditoria_id, Area.id, Area.nombre).join(
            Documento, Documento.id == DocumentoAuditoria.documento_id).join(
            Area, Area.id == Documento.area_id).where(
            DocumentoAuditoria.auditoria_id.in_([row.id for row in rows])).distinct()
        for aid, area_id, name in db.execute(stmt):
            refs.setdefault(aid, []).append(AuditReference(id=area_id, nombre=name))
    result = []
    for row in rows:
        data = AuditoriaRead.model_validate(row)
        data.areas = sorted(refs.get(row.id, []), key=lambda area: area.id)
        result.append(data)
    return result


def filtered_query(user, filters):
    stmt = select(Auditoria).where(authz.auditoria_scope(user))
    if filters.q:
        term = filters.q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        stmt = stmt.where(Auditoria.codigo.ilike('%' + term + '%', escape='\\') |
                          Auditoria.nombre.ilike('%' + term + '%', escape='\\'))
    if filters.estado:
        stmt = stmt.where(Auditoria.estado == filters.estado)
    if filters.responsable_id:
        stmt = stmt.where(Auditoria.responsable_id == filters.responsable_id)
    if filters.area_id:
        stmt = stmt.where(exists(select(DocumentoAuditoria.id).join(
            Documento, Documento.id == DocumentoAuditoria.documento_id).where(
            DocumentoAuditoria.auditoria_id == Auditoria.id, Documento.area_id == filters.area_id)))
    if filters.inicio_desde:
        stmt = stmt.where(Auditoria.fecha_inicio_prevista >= filters.inicio_desde)
    if filters.inicio_hasta:
        stmt = stmt.where(Auditoria.fecha_inicio_prevista <= filters.inicio_hasta)
    return stmt


def list_audits(db, user, filters):
    authz.require_permission(user, 'auditoria.read')
    stmt = filtered_query(user, filters)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = {'id': Auditoria.id.asc(), '-id': Auditoria.id.desc(),
             'fecha_inicio': Auditoria.fecha_inicio_prevista.asc(),
             '-fecha_inicio': Auditoria.fecha_inicio_prevista.desc()}[filters.orden]
    rows = list(db.scalars(stmt.options(joinedload(Auditoria.responsable)).order_by(
        order, Auditoria.id).limit(filters.limit).offset(filters.offset)))
    return read_rows(db, rows), total


def ensure_fresh(row, expected):
    if row.updated_at != naive_utc(expected):
        raise HTTPException(409, 'La auditoria cambio; recargue antes de continuar')


def ensure_dates(row):
    if row.fecha_inicio_prevista and row.fecha_fin_prevista and row.fecha_fin_prevista < row.fecha_inicio_prevista:
        raise HTTPException(422, 'La fecha final prevista no puede preceder a la inicial')


def check_close(row):
    """7C may strengthen preconditions here, inside the already-held row lock."""
    if row.estado != 'IN_REVIEW':
        raise HTTPException(409, 'El cierre requiere una auditoria en revision')


def transaction(db, operation):
    try:
        row = operation()
        db.flush()
        db.commit()
        return row
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        if (exc.orig.args and exc.orig.args[0] == 1062) or getattr(exc.orig, 'sqlite_errorcode', None) == 2067:
            raise HTTPException(409, 'El codigo de auditoria ya existe') from None
        raise HTTPException(422, 'La auditoria incumple una restriccion de datos') from None
    except Exception as exc:
        db.rollback()
        logging.getLogger(__name__).error('Audit mutation failed: %s', type(exc).__name__)
        raise HTTPException(503 if isinstance(exc, SQLAlchemyError) else 500,
                            'No fue posible confirmar la operacion; consulte antes de repetir') from None


def create(db, user, payload):
    def operation():
        authz.authorize_audit_create(db, user, payload)
        authz.lock_actor(db, user.id, 'auditoria.create')
        row = Auditoria(**payload.model_dump(exclude={'created_by_id'}),
                        created_by_id=user.id, estado='PLANNED')
        db.add(row)
        db.flush()
        _log_evento(db, actor=user, accion='CREACION_AUDITORIA', entidad_tipo='AUDITORIA',
                    entidad_id=row.id, correlation_id=str(uuid4()),
                    datos_nuevos={**snapshot(row), 'resultado': 'SUCCESS'})
        return row
    row = transaction(db, operation)
    return read_rows(db, [resource(db, user, row.id)])[0]


def edit(db, user, audit_id, payload):
    def operation():
        row = resource(db, user, audit_id, action='auditoria.update', locking=True)
        ensure_fresh(row, payload.updated_at_esperado)
        if row.estado not in {'PLANNED', 'IN_PROGRESS'}:
            raise HTTPException(409, 'La auditoria no admite edicion en su estado actual')
        old = snapshot(row)
        if 'responsable_id' in payload.model_fields_set:
            authz.authorize_audit_create(db, user, payload)
        for name, value in payload.model_dump(exclude_unset=True, exclude={'updated_at_esperado'}).items():
            setattr(row, name, value)
        ensure_dates(row)
        if snapshot(row) == old:
            raise HTTPException(409, 'No hay cambios de negocio')
        row.updated_by_id = user.id
        _log_evento(db, actor=user, accion='ACTUALIZACION_AUDITORIA', entidad_tipo='AUDITORIA',
                    entidad_id=row.id, correlation_id=str(uuid4()), datos_anteriores=old,
                    datos_nuevos={**snapshot(row), 'resultado': 'SUCCESS'})
        return row
    row = transaction(db, operation)
    return read_rows(db, [resource(db, user, row.id)])[0]


def transition(db, user, audit_id, payload):
    def operation():
        row = resource(db, user, audit_id, action='auditoria.transition', locking=True)
        ensure_fresh(row, payload.updated_at_esperado)
        if row.estado != payload.estado_esperado or payload.estado not in TRANSITIONS.get(row.estado, set()):
            raise HTTPException(409, 'Transicion de estado no permitida')
        if payload.estado == 'COMPLETED':
            check_close(row)
        if payload.estado == 'IN_PROGRESS':
            authz.authorize_audit_create(db, user, row)
        old = snapshot(row)
        action = EVENTS[row.estado, payload.estado]
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if row.estado == 'PLANNED':
            row.iniciada_en = now
        if payload.estado == 'COMPLETED':
            row.completada_en = now
        row.estado = payload.estado
        row.updated_by_id = user.id
        _log_evento(db, actor=user, accion=action, entidad_tipo='AUDITORIA', entidad_id=row.id,
                    correlation_id=str(uuid4()), datos_anteriores=old,
                    datos_nuevos={**snapshot(row), 'resultado': 'SUCCESS'})
        return row
    row = transaction(db, operation)
    return read_rows(db, [resource(db, user, row.id)])[0]


def history(db, user, audit_id, limit, offset):
    resource(db, user, audit_id, action='auditoria.history')
    rows = db.scalars(select(EventoAuditoria).where(EventoAuditoria.entidad_tipo == 'AUDITORIA',
        EventoAuditoria.entidad_id == str(audit_id)).order_by(EventoAuditoria.ocurrido_en.desc(),
        EventoAuditoria.id.desc()).limit(limit).offset(offset))
    def safe(data):
        return {k: v for k, v in data.items() if k in BUSINESS or k == 'resultado'} if data else None
    return [dict(id=row.id, actor_id=row.actor_id, accion=row.accion, ocurrido_en=row.ocurrido_en,
                 datos_anteriores=safe(row.datos_anteriores), datos_nuevos=safe(row.datos_nuevos)) for row in rows]
