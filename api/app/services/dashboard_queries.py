"""SQL builders: scopes precede aggregation, ordering and pagination."""
from sqlalchemy import select, exists, and_, false, case, literal, union_all, cast, String, type_coerce
from sqlalchemy.dialects import mysql

from app.models.entities import (Auditoria, Hallazgo, Documento, VersionDocumento,
    DocumentoAuditoria, RondaAprobacion, DecisionAprobacion, Evidencia, EventoAuditoria)
from app.services import authorization_service as authz

AUDIT_STATES = ('PLANNED', 'IN_PROGRESS', 'IN_REVIEW', 'COMPLETED', 'CANCELLED')
FINDING_STATES = ('OPEN', 'IN_PROGRESS', 'PENDING_VERIFICATION', 'CLOSED', 'ACCEPTED_RISK')
ROUND_STATES = ('PENDING', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'CHANGES_REQUESTED', 'CANCELLED')
DECISION_STATES = ('PENDING', 'APPROVED', 'REJECTED', 'CHANGES_REQUESTED')
EVIDENCE_TYPES = ('FILE', 'REFERENCE', 'NOTE', 'OTHER')

RESOURCES = {
    'auditoria': (Auditoria, 'auditoria.read', authz.auditoria_scope),
    'hallazgo': (Hallazgo, 'hallazgo.read', authz.hallazgo_scope),
    'documento': (Documento, 'documento.read', authz.documento_scope),
    'version': (VersionDocumento, 'version.read', authz.version_scope),
    'aprobacion': (RondaAprobacion, 'aprobacion.read', authz.ronda_scope),
    'evidencia': (Evidencia, 'evidencia.read', authz.evidencia_scope),
}


def permitted(user, action):
    return user.rol == 'ADMIN' or user.rol in authz.PERMISSIONS.get(action, set())


def canonical_text(column):
    """Exact whitelist matching even with MySQL's case/accent-insensitive CHECKs."""
    # Retain string bind processing: PyMySQL's binary processor requires bytes,
    # while the whitelisted values are strings. This changes no SQL semantics.
    return type_coerce(cast(column, String(80).with_variant(mysql.BINARY(), 'mysql')), String(80))


def context_link(audit_id, document_id, version_id=None):
    conditions = [DocumentoAuditoria.auditoria_id == audit_id,
                  DocumentoAuditoria.documento_id == document_id]
    if version_id is not None:
        conditions.append(DocumentoAuditoria.version_documento_id == version_id)
    return exists(select(DocumentoAuditoria.id).where(*conditions)
                  .correlate_except(DocumentoAuditoria))


def scope(user, resource, audit_id=None):
    model, action, builder = RESOURCES[resource]
    condition = builder(user) if permitted(user, action) else false()
    if audit_id is None:
        return condition
    if resource == 'auditoria':
        context = Auditoria.id == audit_id
    elif resource in {'hallazgo', 'evidencia'}:
        context = model.auditoria_id == audit_id
    elif resource == 'documento':
        context = context_link(audit_id, Documento.id)
    elif resource == 'version':
        # Documentary reading includes all readable versions of the linked document (6B.2).
        context = context_link(audit_id, VersionDocumento.documento_id)
    else:
        context = exists(select(VersionDocumento.id).where(
            VersionDocumento.id == RondaAprobacion.version_documento_id,
            context_link(audit_id, VersionDocumento.documento_id, VersionDocumento.id))
            .correlate_except(VersionDocumento))
    return and_(condition, context)


def decision_scope(user, audit_id=None):
    # 7C permits reading all decisions in a readable round, including colleagues.
    return exists(select(RondaAprobacion.id).where(
        RondaAprobacion.id == DecisionAprobacion.ronda_aprobacion_id,
        scope(user, 'aprobacion', audit_id)).correlate_except(RondaAprobacion))


def has_version(user):
    return exists(select(VersionDocumento.id).where(
        VersionDocumento.documento_id == Documento.id,
        scope(user, 'version')).correlate_except(VersionDocumento))


def alert_query(user, filters):
    aid = filters.auditoria_id
    def projection(model, resource, kind, severity, name, date, condition):
        return select(kind.label('tipo'), severity.label('severidad'),
            literal(resource).label('recurso'), model.id.label('recurso_id'),
            name.label('nombre'), date.label('fecha')).where(scope(user, resource, aid), condition)
    audit_review = canonical_text(Auditoria.estado) == 'IN_REVIEW'
    audits = projection(Auditoria, 'auditoria',
        case((audit_review, 'AUDITORIA_REVISION'), else_='AUDITORIA_ACTIVA'),
        literal('INFO'), Auditoria.nombre, Auditoria.updated_at,
        canonical_text(Auditoria.estado).in_(('IN_PROGRESS', 'IN_REVIEW')))
    active_parent = exists(select(Auditoria.id).where(Auditoria.id == Hallazgo.auditoria_id,
        scope(user, 'auditoria', aid), canonical_text(Auditoria.estado).in_(('IN_PROGRESS', 'IN_REVIEW')))
        .correlate_except(Auditoria))
    findings = projection(Hallazgo, 'hallazgo', literal('HALLAZGO_PENDIENTE'),
        literal('WARNING'), Hallazgo.titulo, Hallazgo.updated_at,
        and_(canonical_text(Hallazgo.estado).in_(('OPEN', 'IN_PROGRESS', 'PENDING_VERIFICATION')), active_parent))
    own = and_(literal(user.rol == 'APROBADOR'), canonical_text(RondaAprobacion.estado) == 'IN_REVIEW',
        exists(select(DecisionAprobacion.id).where(
            DecisionAprobacion.ronda_aprobacion_id == RondaAprobacion.id,
            DecisionAprobacion.aprobador_id == user.id, canonical_text(DecisionAprobacion.estado) == 'PENDING')
            .correlate_except(DecisionAprobacion)))
    # These INFO alerts describe the registered round/assignment state. They do
    # not claim a command is available: 7C can block shared versions on hidden
    # terminal audits. Looking up those hidden audits here would leak aggregates.
    rounds = projection(RondaAprobacion, 'aprobacion',
        case((own, 'DECISION_PROPIA_PENDIENTE'), else_='RONDA_PENDIENTE'),
        literal('INFO'), literal('Ronda de aprobación'), RondaAprobacion.updated_at,
        canonical_text(RondaAprobacion.estado).in_(('PENDING', 'IN_REVIEW')))
    documents = projection(Documento, 'documento', literal('DOCUMENTO_SIN_VERSION'),
        literal('WARNING'), Documento.titulo, Documento.updated_at,
        and_(literal(user.rol != 'APROBADOR'), ~has_version(user),
             canonical_text(Documento.estado).in_(('DRAFT', 'ACTIVE'))))
    derived = union_all(audits, findings, rounds, documents).subquery()
    stmt = select(derived)
    if filters.tipo is not None:
        stmt = stmt.where(derived.c.tipo == filters.tipo)
    if filters.severidad is not None:
        stmt = stmt.where(derived.c.severidad == filters.severidad)
    return stmt


# History permissions are stricter than resource.read. Never broaden them for activity.
EVENTS = {
    'auditoria': ('AUDITORIA', 'auditoria.history', ('CREACION_AUDITORIA',
        'ACTUALIZACION_AUDITORIA', 'ACTIVACION_AUDITORIA', 'REVISION_AUDITORIA',
        'REACTIVACION_AUDITORIA', 'CIERRE_AUDITORIA')),
    'hallazgo': ('HALLAZGO', 'hallazgo.history', ('CREACION_HALLAZGO',
        'ACTUALIZACION_HALLAZGO', 'CAMBIO_ESTADO_HALLAZGO', 'ASOCIACION_EVIDENCIA_HALLAZGO')),
    'documento': ('DOCUMENTO', 'historial.read', ('CREACION_DOCUMENTO',
        'ACTUALIZACION_DOCUMENTO', 'CREACION_VERSION')),
    'aprobacion': ('RONDA_APROBACION', 'aprobacion.history', ('CREACION_RONDA_APROBACION',
        'INICIO_RONDA_APROBACION', 'DECISION_APROBACION', 'CIERRE_RONDA_APROBACION')),
}


def activity_query(user, context):
    projections = []
    for resource, (entity, permission, actions) in EVENTS.items():
        if not permitted(user, permission):
            continue
        model = RESOURCES[resource][0]
        # Binary RHS avoids connection/table collation conflicts on MySQL and
        # makes legacy IDs canonical strings (no numeric coercion of 1e0/1junk).
        canonical_id = canonical_text(cast(model.id, String(80)))
        projections.append(select(EventoAuditoria.id, EventoAuditoria.accion,
            EventoAuditoria.ocurrido_en, model.id.label('recurso_id'), literal(resource).label('recurso'))
            .join(model, EventoAuditoria.entidad_id == canonical_id)
            .where(canonical_text(EventoAuditoria.entidad_tipo) == entity,
                   canonical_text(EventoAuditoria.accion).in_(actions),
                   scope(user, resource, context.auditoria_id)))
    if not projections:
        return select(EventoAuditoria.id, EventoAuditoria.accion, EventoAuditoria.ocurrido_en,
            literal(1).label('recurso_id'), literal('aprobacion').label('recurso')).where(false())
    return select(union_all(*projections).subquery())
