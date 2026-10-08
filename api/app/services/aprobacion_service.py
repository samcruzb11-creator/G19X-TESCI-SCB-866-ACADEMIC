"""Version approval rounds on schema 005; all writes share 7A's audit locks."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import logging
from fastapi import HTTPException
from sqlalchemy import select, func, exists
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import joinedload
from app.models.entities import (RondaAprobacion as Ronda, DecisionAprobacion as Decision,
    VersionDocumento as Version, Documento, DocumentoAuditoria as Link, Auditoria, Usuario, EventoAuditoria)
from app.schemas.aprobacion import RondaRead, DecisionRead, ApprovalResource
from app.schemas.auditoria import naive_utc, AuditEventRead
from app.services import authorization_service as authz
from app.services.documento_service import _log_evento

ACTIVE = {'PENDING', 'IN_REVIEW'}
TERMINAL_AUDITS = {'COMPLETED', 'CANCELLED'}


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
    except OperationalError as exc:
        db.rollback()
        code = exc.orig.args[0] if getattr(exc.orig, 'args', None) else None
        if code in {1205, 1213}:
            raise HTTPException(409, 'Conflicto concurrente; recargue antes de continuar') from None
        raise HTTPException(503, 'No fue posible confirmar la operacion; consulte antes de repetir') from None
    except Exception as exc:
        db.rollback()
        logging.getLogger(__name__).error('Approval mutation failed: %s', type(exc).__name__)
        raise HTTPException(503 if isinstance(exc, SQLAlchemyError) else 500,
            'No fue posible confirmar la operacion; consulte antes de repetir') from None


def resource(db, user, round_id, action='aprobacion.read'):
    return authz.resource(db, user, Ronda, round_id, action, authz.ronda_scope)


def contextual_link(user, audit_id, version_id, document_id):
    return exists(select(Link.id).join(Auditoria, Link.auditoria_id == Auditoria.id).where(
        Link.auditoria_id == audit_id, Link.version_documento_id == version_id,
        Link.documento_id == document_id, authz.auditoria_scope(user)).correlate_except(Link, Auditoria))


def filter_context(db, user, filters, stmt):
    if filters.documento_id is not None:
        authz.resource(db, user, Documento, filters.documento_id, 'documento.read', authz.documento_scope)
        stmt = stmt.where(Version.documento_id == filters.documento_id)
    if getattr(filters, 'version_documento_id', None) is not None:
        authz.resource(db, user, Version, filters.version_documento_id, 'version.read', authz.approval_version_scope)
        stmt = stmt.where(Version.id == filters.version_documento_id)
    if filters.auditoria_id is not None:
        authz.resource(db, user, Auditoria, filters.auditoria_id, 'auditoria.read', authz.auditoria_scope)
        stmt = stmt.where(contextual_link(user, filters.auditoria_id, Version.id, Version.documento_id))
    return stmt


def lock_subject(db, user, version_id, document_id, action, audit_id=None):
    authz.require_permission(user, action)
    conditions = [Version.id == version_id, Version.documento_id == document_id,
        authz.approval_version_scope(user)]
    if audit_id is not None:
        conditions.append(contextual_link(user, audit_id, Version.id, Version.documento_id))
    if db.scalar(select(Version.id).where(*conditions)) is None:
        raise HTTPException(404, 'Recurso no encontrado')
    # Current locking reads defeat an older REPEATABLE READ snapshot. Locks on
    # every linked audit prevent bypass through a second, open audit context.
    audit_ids = db.scalars(select(Auditoria.id).where(exists(select(Link.id).where(
        Link.auditoria_id == Auditoria.id, Link.version_documento_id == version_id)
        .correlate_except(Link))).order_by(Auditoria.id)).all()
    # Point locks give a deterministic order even if a JOIN/EXISTS optimizer
    # would perform filesort after acquiring rows in a different order.
    audits = [db.scalar(select(Auditoria).where(Auditoria.id == id).with_for_update()
        .execution_options(populate_existing=True)) for id in audit_ids]
    if any(a is None for a in audits):
        raise HTTPException(409, 'El contexto documental cambio; recargue antes de continuar')
    if user.rol in authz.AUDITORES and not any(a.responsable_id == user.id and
            (audit_id is None or a.id == audit_id) for a in audits):
        # A nested EXISTS can have used an earlier consistent-read snapshot.
        # The locked parent rows are authoritative after an ownership change.
        raise HTTPException(404, 'Recurso no encontrado')
    if any(a.estado not in {'PLANNED', 'IN_PROGRESS', 'IN_REVIEW'} for a in audits):
        raise HTTPException(409, 'Una auditoria vinculada no admite aprobaciones')
    doc = db.scalar(select(Documento).where(Documento.id == document_id,
        authz.documento_scope(user)).with_for_update().execution_options(populate_existing=True))
    version = db.scalar(select(Version).where(*conditions).with_for_update()
        .execution_options(populate_existing=True))
    if doc is None or version is None:
        raise HTTPException(404, 'Recurso no encontrado')
    links = db.scalars(select(Link).where(Link.version_documento_id == version_id)
        .order_by(Link.id).with_for_update().execution_options(populate_existing=True)).all()
    if any(link.documento_id != document_id for link in links):
        raise HTTPException(404, 'Recurso no encontrado')
    if {link.auditoria_id for link in links} != {a.id for a in audits}:
        raise HTTPException(409, 'El contexto documental cambio; recargue antes de continuar')
    return version, [a.id for a in audits]


def lock_round(db, user, round_id, action):
    initial = resource(db, user, round_id, action)
    version = db.get(Version, initial.version_documento_id)
    _, audits = lock_subject(db, user, version.id, version.documento_id, action)
    row = db.scalar(select(Ronda).where(Ronda.id == round_id, authz.ronda_scope(user))
        .with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404, 'Recurso no encontrado')
    return row, audits


def lock_actor(db, user, action, assigned=None):
    ids = sorted(set([user.id, *(assigned or [])]))
    rows = db.scalars(select(Usuario).where(Usuario.id.in_(ids)).order_by(Usuario.id)
        .with_for_update().execution_options(populate_existing=True)).all()
    actors = {u.id: u for u in rows}
    actor = actors.get(user.id)
    if actor is None or not actor.activo:
        raise HTTPException(403, 'Operacion no permitida')
    authz.require_permission(actor, action)
    if action == 'aprobacion.decide' and actor.rol != 'APROBADOR':
        raise HTTPException(403, 'La decision requiere un aprobador activo asignado')
    if assigned is not None and any(i not in actors or not actors[i].activo or
                                    actors[i].rol != 'APROBADOR' for i in assigned):
        raise HTTPException(404, 'Recurso no encontrado')
    return actor


def touch(row):
    row.updated_at = max(now(), row.updated_at + timedelta(microseconds=1))


def manage_scope_after_actor_lock(db, actor, version_id, audit_id=None):
    if actor.rol == 'AUDITOR_INTERNO':
        stmt = select(Auditoria.id).where(Auditoria.responsable_id == actor.id,
            exists(select(Link.id).where(Link.auditoria_id == Auditoria.id,
                Link.version_documento_id == version_id).correlate_except(Link)))
        if audit_id is not None:
            stmt = stmt.where(Auditoria.id == audit_id)
        # Direct locking read of the ownership column, including when ADMIN
        # changed role during an earlier wait. Never trust a subquery snapshot.
        if db.scalar(stmt.order_by(Auditoria.id).limit(1).with_for_update()) is None:
            raise HTTPException(404, 'Recurso no encontrado')


def log(db, actor, row, audits, action, data=None, old=None):
    version = db.get(Version, row.version_documento_id)
    _log_evento(db, actor=actor, accion=action, entidad_tipo='RONDA_APROBACION', entidad_id=row.id,
        correlation_id=str(uuid4()), datos_anteriores=old,
        datos_nuevos={'ronda_id': row.id, 'version_documento_id': version.id,
            'documento_id': version.documento_id, 'auditorias_ids': audits,
            'estado': row.estado, **(data or {})})


def decision_rows(db, round_id, locking=False):
    stmt = select(Decision).where(Decision.ronda_aprobacion_id == round_id).order_by(Decision.id)
    if locking:
        stmt = stmt.with_for_update()
    else:
        stmt = stmt.options(joinedload(Decision.aprobador))
    return db.scalars(stmt.execution_options(populate_existing=True)).all()


def result(decisions):
    if not decisions or any(d.estado == 'PENDING' for d in decisions):
        return None
    states = {d.estado for d in decisions}
    return 'REJECTED' if 'REJECTED' in states else 'CHANGES_REQUESTED' if 'CHANGES_REQUESTED' in states else 'APPROVED'


def close(db, actor, row, audits, outcome):
    previous = row.estado
    row.estado = outcome
    row.resuelta_en = now()
    touch(row)
    log(db, actor, row, audits, 'CIERRE_RONDA_APROBACION', old={'estado': previous})


def create(db, user, payload):
    def operation():
        _, audits = lock_subject(db, user, payload.version_documento_id, payload.documento_id,
            'aprobacion.manage', payload.auditoria_id)
        # Version row serializes equivalent creation and numbering; read current
        # rows, not MAX from an earlier InnoDB consistent-read snapshot.
        active = db.scalar(select(Ronda.id).where(Ronda.version_documento_id == payload.version_documento_id,
            Ronda.estado.in_(ACTIVE)).limit(1).with_for_update())
        if active is not None:
            raise HTTPException(409, 'Ya existe una ronda activa para esta version')
        previous = db.scalar(select(Ronda.numero_ronda).where(Ronda.version_documento_id == payload.version_documento_id)
            .order_by(Ronda.numero_ronda.desc()).limit(1).with_for_update())
        number = (previous or 0) + 1
        if number > 4294967295:
            raise HTTPException(409, 'Limite de rondas alcanzado')
        actor = lock_actor(db, user, 'aprobacion.manage', payload.aprobadores_ids)
        manage_scope_after_actor_lock(db, actor, payload.version_documento_id, payload.auditoria_id)
        # Eligibility/role changes during lock waits must recheck resource scope.
        if db.scalar(select(Version.id).where(Version.id == payload.version_documento_id,
            authz.approval_version_scope(actor)).with_for_update()) is None:
            raise HTTPException(404, 'Recurso no encontrado')
        row = Ronda(version_documento_id=payload.version_documento_id, numero_ronda=number,
                    estado='PENDING', solicitada_por_id=actor.id)
        db.add(row); db.flush()
        for approver in sorted(payload.aprobadores_ids):
            db.add(Decision(ronda_aprobacion_id=row.id, aprobador_id=approver, estado='PENDING'))
        log(db, actor, row, audits, 'CREACION_RONDA_APROBACION',
            {'aprobadores_ids': sorted(payload.aprobadores_ids), 'numero_ronda': number})
        return row.id
    round_id = transaction(db, operation)
    return detail(db, user, round_id)


def command(db, user, round_id, payload, action):
    def operation():
        row, audits = lock_round(db, user, round_id, 'aprobacion.manage')
        decisions = decision_rows(db, row.id, True)
        actor = lock_actor(db, user, 'aprobacion.manage',
            [d.aprobador_id for d in decisions] if action == 'iniciar' else None)
        manage_scope_after_actor_lock(db, actor, row.version_documento_id)
        if db.scalar(select(Ronda.id).where(Ronda.id == row.id, authz.ronda_scope(actor)).with_for_update()) is None:
            raise HTTPException(404, 'Recurso no encontrado')
        if row.estado != payload.estado_esperado or row.updated_at != naive_utc(payload.updated_at_esperado):
            raise HTTPException(409, 'La ronda cambio; recargue antes de continuar')
        if row.estado not in ACTIVE:
            raise HTTPException(409, 'La ronda es terminal')
        if action == 'iniciar':
            if row.estado != 'PENDING' or not decisions:
                raise HTTPException(409, 'La ronda no admite inicio')
            row.estado = 'IN_REVIEW'; touch(row)
            log(db, actor, row, audits, 'INICIO_RONDA_APROBACION', old={'estado': 'PENDING'})
        elif action == 'cancelar':
            close(db, actor, row, audits, 'CANCELLED')
        elif action == 'finalizar':
            outcome = result(decisions)
            if row.estado != 'IN_REVIEW' or outcome is None:
                raise HTTPException(409, 'Faltan decisiones para finalizar la ronda')
            close(db, actor, row, audits, outcome)
        else:
            raise HTTPException(422, 'Comando invalido')
    transaction(db, operation)
    return detail(db, user, round_id)


def decide(db, user, round_id, payload):
    def operation():
        row, audits = lock_round(db, user, round_id, 'aprobacion.decide')
        decisions = decision_rows(db, row.id, True)
        own = next((d for d in decisions if d.aprobador_id == user.id), None)
        if own is None:
            raise HTTPException(404, 'Recurso no encontrado')
        actor = lock_actor(db, user, 'aprobacion.decide')
        if row.estado != 'IN_REVIEW' or own.estado != 'PENDING':
            raise HTTPException(409, 'La ronda o decision no admite cambios')
        if own.updated_at != naive_utc(payload.updated_at_esperado):
            raise HTTPException(409, 'La asignacion cambio; recargue antes de continuar')
        own.estado = payload.estado; own.comentario = payload.comentario
        own.decidida_en = now(); touch(own); touch(row)
        log(db, actor, row, audits, 'DECISION_APROBACION',
            {'decision_id': own.id, 'aprobador_id': actor.id, 'decision': own.estado})
        outcome = result(decisions)
        if outcome is not None:
            close(db, actor, row, audits, outcome)
    transaction(db, operation)
    return detail(db, user, round_id)


def read_query(user):
    total = select(func.count()).select_from(Decision).where(Decision.ronda_aprobacion_id == Ronda.id).correlate(Ronda).scalar_subquery()
    pending = select(func.count()).select_from(Decision).where(Decision.ronda_aprobacion_id == Ronda.id,
        Decision.estado == 'PENDING').correlate(Ronda).scalar_subquery()
    return (select(Ronda, Version, Documento, total, pending).join(Version,
        Ronda.version_documento_id == Version.id).join(Documento, Version.documento_id == Documento.id)
        .where(authz.ronda_scope(user)).options(joinedload(Ronda.solicitada_por)))


def serialize(db, user, rows):
    # One bounded query for own assignments across the page (no per-row lazy loads).
    ids = [r[0].id for r in rows]
    own = {d.ronda_aprobacion_id: DecisionRead.model_validate(d) for d in db.scalars(
        select(Decision).where(Decision.ronda_aprobacion_id.in_(ids), Decision.aprobador_id == user.id)
        .options(joinedload(Decision.aprobador)).execution_options(populate_existing=True))} if ids else {}
    # Terminal guards affect UX without exposing the IDs of other audit contexts.
    blocked = set(db.scalars(select(Link.version_documento_id).join(Auditoria, Link.auditoria_id == Auditoria.id)
        .where(Link.version_documento_id.in_([r[1].id for r in rows]), Auditoria.estado.in_(TERMINAL_AUDITS)))) if ids else set()
    output = []
    for row, version, doc, total, pending in rows:
        mine = own.get(row.id)
        output.append(RondaRead(id=row.id, numero_ronda=row.numero_ronda, estado=row.estado,
            documento_id=doc.id, documento_titulo=doc.titulo, version_documento_id=version.id,
            numero_version=version.numero_version, solicitada_por=row.solicitada_por,
            solicitada_en=row.solicitada_en, resuelta_en=row.resuelta_en, created_at=row.created_at,
            updated_at=row.updated_at, decisiones_count=total, pendientes_count=pending,
            mi_decision=mine, puede_decidir=user.activo and user.rol == 'APROBADOR' and mine is not None
                and mine.estado == 'PENDING' and row.estado == 'IN_REVIEW' and version.id not in blocked,
            puede_gestionar=user.rol in {'ADMIN', 'AUDITOR_INTERNO'} and row.estado in ACTIVE and version.id not in blocked))
    return output


def detail(db, user, round_id):
    authz.require_permission(user, 'aprobacion.read')
    row = db.execute(read_query(user).where(Ronda.id == round_id).execution_options(populate_existing=True)).first()
    if row is None:
        raise HTTPException(404, 'Recurso no encontrado')
    return serialize(db, user, [row])[0]


def list_rounds(db, user, filters):
    authz.require_permission(user, 'aprobacion.read')
    stmt = filter_context(db, user, filters, read_query(user))
    if filters.estado:
        stmt = stmt.where(Ronda.estado == filters.estado)
    if filters.pendientes_propias:
        stmt = stmt.where(Ronda.estado == 'IN_REVIEW', exists(select(Decision.id).where(
            Decision.ronda_aprobacion_id == Ronda.id, Decision.aprobador_id == user.id,
            Decision.estado == 'PENDING').correlate_except(Decision)))
    if filters.q:
        term = filters.q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        stmt = stmt.where(Documento.titulo.ilike('%' + term + '%', escape='\\'))
    count = db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = Ronda.id.desc() if filters.orden == '-id' else Ronda.id.asc()
    rows = db.execute(stmt.order_by(order).offset(filters.offset).limit(filters.limit)
        .execution_options(populate_existing=True)).all()
    return serialize(db, user, rows), count


def decisions(db, user, round_id, page):
    resource(db, user, round_id)
    visible = exists(select(Ronda.id).where(Ronda.id == round_id, authz.ronda_scope(user)).correlate_except(Ronda))
    stmt = select(Decision).where(Decision.ronda_aprobacion_id == round_id, visible).options(joinedload(Decision.aprobador))
    count = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Decision.id).offset(page.offset).limit(page.limit)
        .execution_options(populate_existing=True))
    return [DecisionRead.model_validate(d) for d in rows], count


def history(db, user, round_id, page):
    resource(db, user, round_id, 'aprobacion.history')
    stmt = select(EventoAuditoria).where(EventoAuditoria.entidad_tipo == 'RONDA_APROBACION',
        EventoAuditoria.entidad_id == str(round_id), exists(select(Ronda.id).where(
            Ronda.id == round_id, authz.ronda_scope(user)).correlate_except(Ronda)))
    count = db.scalar(select(func.count()).select_from(stmt.subquery()))
    whitelist = {'ronda_id', 'version_documento_id', 'documento_id', 'estado', 'decision_id',
                 'aprobador_id', 'decision', 'numero_ronda'}
    def safe(data):
        return {k: v for k, v in (data or {}).items() if k in whitelist} if data is not None else None
    return [AuditEventRead(id=e.id, actor_id=e.actor_id, accion=e.accion, ocurrido_en=e.ocurrido_en,
        datos_anteriores=safe(e.datos_anteriores), datos_nuevos=safe(e.datos_nuevos))
        for e in db.scalars(stmt.order_by(EventoAuditoria.id.desc()).offset(page.offset).limit(page.limit))], count


def resources(db, user, filters):
    authz.require_permission(user, 'aprobacion.manage')
    stmt = select(Version.id, Version.numero_version, Documento.id, Documento.titulo).join(Documento,
        Version.documento_id == Documento.id).where(authz.approval_version_scope(user))
    stmt = filter_context(db, user, filters, stmt)
    count = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return [ApprovalResource(version_documento_id=v, numero_version=n, documento_id=d, documento_titulo=t)
        for v, n, d, t in db.execute(stmt.order_by(Version.id).offset(filters.offset).limit(filters.limit))], count


def approvers(db, user, filters):
    authz.require_permission(user, 'aprobacion.manage')
    stmt = select(Usuario.id, Usuario.nombre).where(Usuario.activo.is_(True), authz.exact_role(Usuario.rol) == 'APROBADOR')
    if filters.q:
        term = filters.q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        stmt = stmt.where(Usuario.nombre.ilike('%' + term + '%', escape='\\'))
    count = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return [{'id': i, 'nombre': n} for i, n in db.execute(stmt.order_by(Usuario.id)
        .offset(filters.offset).limit(filters.limit))], count
