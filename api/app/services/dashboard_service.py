"""Bounded read projections; no mutation, global cache or ORM lazy loading."""
from datetime import datetime, timezone
from sqlalchemy import select, func, case, literal
from fastapi import HTTPException

from app.models.entities import Auditoria, Hallazgo, Documento, VersionDocumento, RondaAprobacion, DecisionAprobacion, Evidencia
from app.schemas.dashboard import (Distribution, Ratio, Documents, Decisions, Indicators,
    Alert, AlertPage, Activity, ActivityPage, Summary, AlertFilters)
from app.services import dashboard_queries as queries
from app.services import authorization_service as authz

ALERT_TEXT = {
    'AUDITORIA_ACTIVA': ('Auditoría en curso', 'Auditoría registrada en IN_PROGRESS. Consulta su seguimiento.'),
    'AUDITORIA_REVISION': ('Auditoría en revisión', 'Auditoría registrada en IN_REVIEW. Consulta la revisión.'),
    'HALLAZGO_PENDIENTE': ('Hallazgo sin resolver', 'Hallazgo OPEN, IN_PROGRESS o PENDING_VERIFICATION en una auditoría activa.'),
    'RONDA_PENDIENTE': ('Ronda pendiente registrada', 'Estado PENDING o IN_REVIEW. Consulta el detalle para conocer las acciones disponibles.'),
    'DECISION_PROPIA_PENDIENTE': ('Mi decisión pendiente registrada', 'Asignación propia PENDING en ronda IN_REVIEW. Consulta el detalle para conocer si admite una decisión.'),
    'DOCUMENTO_SIN_VERSION': ('Documento sin versión', 'Documento DRAFT o ACTIVE sin ninguna versión registrada.'),
}
EVENT_TEXT = {
    'CREACION_AUDITORIA': 'Auditoría creada', 'ACTUALIZACION_AUDITORIA': 'Auditoría actualizada',
    'ACTIVACION_AUDITORIA': 'Auditoría iniciada', 'REVISION_AUDITORIA': 'Auditoría en revisión',
    'REACTIVACION_AUDITORIA': 'Auditoría reactivada', 'CIERRE_AUDITORIA': 'Auditoría completada',
    'CREACION_HALLAZGO': 'Hallazgo creado', 'ACTUALIZACION_HALLAZGO': 'Hallazgo actualizado',
    'CAMBIO_ESTADO_HALLAZGO': 'Estado de hallazgo actualizado',
    'ASOCIACION_EVIDENCIA_HALLAZGO': 'Evidencia vinculada a hallazgo',
    'CREACION_DOCUMENTO': 'Documento creado', 'ACTUALIZACION_DOCUMENTO': 'Documento actualizado',
    'CREACION_VERSION': 'Versión registrada', 'CREACION_RONDA_APROBACION': 'Ronda creada',
    'INICIO_RONDA_APROBACION': 'Ronda iniciada', 'DECISION_APROBACION': 'Decisión registrada',
    'CIERRE_RONDA_APROBACION': 'Ronda cerrada',
}


def validate_context(db, user, context):
    # Effective domain roles only. CONSULTA is absent from schema/RBAC.
    if not user.activo or user.rol not in {'ADMIN', *authz.AUDITORES, 'RESPONSABLE_AREA', 'APROBADOR'}:
        raise HTTPException(403, 'Operacion no permitida')
    if context.auditoria_id is not None:
        authz.require_permission(user, 'auditoria.read')
        if db.scalar(select(Auditoria.id).where(Auditoria.id == context.auditoria_id,
                authz.auditoria_scope(user))) is None:
            raise HTTPException(404, 'Recurso no encontrado')


def ratio(numerator=0, denominator=0, applicable=True):
    return Ratio(numerador=numerator, denominador=denominator,
        porcentaje=round(100 * numerator / denominator, 2) if applicable and denominator else None,
        estado='NOT_APPLICABLE' if not applicable else 'OK' if denominator else 'NO_DATA')


def grouped(db, user, context, resource, column, states):
    if not queries.permitted(user, queries.RESOURCES[resource][1]):
        return None
    state_key = case((queries.canonical_text(column).in_(states), column), else_='DESCONOCIDO')
    rows = db.execute(select(state_key, func.count()).where(queries.scope(user, resource,
        context.auditoria_id)).group_by(state_key)).all()
    counts = dict.fromkeys((*states, 'DESCONOCIDO'), 0)
    for state, count in rows:
        counts[state] += count
    return Distribution(total=sum(counts.values()), por_estado=counts)


def indicators(db, user, context):
    audits = grouped(db, user, context, 'auditoria', Auditoria.estado, queries.AUDIT_STATES)
    findings = grouped(db, user, context, 'hallazgo', Hallazgo.estado, queries.FINDING_STATES)
    rounds = grouped(db, user, context, 'aprobacion', RondaAprobacion.estado, queries.ROUND_STATES)
    evidence = grouped(db, user, context, 'evidencia', Evidencia.tipo, queries.EVIDENCE_TYPES)
    decisions = None
    if rounds is not None:
        state_key = case((queries.canonical_text(DecisionAprobacion.estado).in_(queries.DECISION_STATES),
                          DecisionAprobacion.estado), else_='DESCONOCIDO')
        rows = db.execute(select(state_key, func.count(),
            func.sum(case((DecisionAprobacion.aprobador_id == user.id, 1), else_=0)))
            .where(queries.decision_scope(user, context.auditoria_id)).group_by(state_key)).all()
        counts = dict.fromkeys((*queries.DECISION_STATES, 'DESCONOCIDO'), 0)
        pending_own = 0
        for state, count, own in rows:
            counts[state] += count
            if state == 'PENDING':
                pending_own += int(own or 0)
        decisions = Decisions(total=sum(counts.values()), por_estado=counts,
            resueltas=sum(counts[s] for s in ('APPROVED', 'REJECTED', 'CHANGES_REQUESTED')),
            pendientes_propias=pending_own if user.rol == 'APROBADOR' else None)
    documents = None
    coverage = ratio(applicable=False)
    if queries.permitted(user, 'documento.read'):
        # APROBADOR cannot measure absence across versions it cannot read;
        # do not even run the unused coverage subquery for that role.
        missing_expression = literal(0) if user.rol == 'APROBADOR' else func.sum(case(
            (~queries.has_version(user), 1), else_=0))
        total, missing = db.execute(select(func.count(), missing_expression).select_from(Documento)
            .where(queries.scope(user, 'documento', context.auditoria_id))).one()
        versions = db.scalar(select(func.count()).select_from(VersionDocumento).where(
            queries.scope(user, 'version', context.auditoria_id)))
        missing = int(missing or 0) if user.rol != 'APROBADOR' else None
        documents = Documents(total=total, versiones=versions, sin_version=missing)
        if missing is not None:
            coverage = ratio(total - missing, total)
    def state_ratio(group, numerator_states, excluded=()):
        if group is None:
            return ratio(applicable=False)
        return ratio(sum(group.por_estado[s] for s in numerator_states),
            group.total - sum(group.por_estado[s] for s in excluded))
    return Indicators(auditorias=audits, hallazgos=findings, aprobaciones=rounds,
        decisiones=decisions, documentos=documents, evidencias=evidence,
        auditorias_completadas=state_ratio(audits, ('COMPLETED',), ('CANCELLED',)),
        hallazgos_cerrados=state_ratio(findings, ('CLOSED',)),
        rondas_resueltas=state_ratio(rounds, ('APPROVED', 'REJECTED', 'CHANGES_REQUESTED'), ('CANCELLED',)),
        documentos_con_version=coverage)


def alerts(db, user, filters):
    stmt = queries.alert_query(user, filters)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    cols = stmt.selected_columns
    rows = db.execute(stmt.order_by(case((cols.severidad == 'WARNING', 0), else_=1),
        cols.fecha.desc(), cols.tipo, cols.recurso_id).limit(filters.limit).offset(filters.offset)).mappings()
    items = []
    for row in rows:
        title, description = ALERT_TEXT[row['tipo']]
        items.append(Alert(**row, clave=f"{row['tipo']}:{row['recurso']}:{row['recurso_id']}",
            titulo=title, descripcion=description,
            destino={'pagina': row['recurso'], 'id': row['recurso_id']}))
    return AlertPage(total=total, limit=filters.limit, offset=filters.offset, items=items)


def activity(db, user, page):
    stmt = queries.activity_query(user, page)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    cols = stmt.selected_columns
    rows = db.execute(stmt.order_by(cols.ocurrido_en.desc(), cols.id.desc())
        .limit(page.limit).offset(page.offset)).mappings()
    return ActivityPage(total=total, limit=page.limit, offset=page.offset,
        items=[Activity(id=r['id'], accion=r['accion'], titulo=EVENT_TEXT[r['accion']],
            ocurrido_en=r['ocurrido_en'], destino={'pagina':r['recurso'], 'id':r['recurso_id']}) for r in rows])


def summary(db, user, page):
    return Summary(generado_en=datetime.now(timezone.utc), indicadores=indicators(db, user, page),
        alertas=alerts(db, user, AlertFilters(**page.model_dump())), actividad=activity(db, user, page))
