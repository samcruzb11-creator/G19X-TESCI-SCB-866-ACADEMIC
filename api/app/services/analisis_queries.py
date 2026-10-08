"""Scope-first SQL; windows generate O(n) detections, never all duplicate pairs."""
from sqlalchemy import select, func, literal, case, union_all, and_, or_, false, exists
from app.models.entities import (Documento, VersionDocumento, Evidencia, Hallazgo,
    HallazgoEvidencia, DocumentoAuditoria, Auditoria)
from app.services import dashboard_queries as scopes
from app.services import authorization_service as authz


def valid_hash(column):
    # LOWER preserves hexadecimal equivalence; anchors/length reject CHAR padding.
    return and_(func.length(column) == 64,
                column.regexp_match('^[0-9a-fA-F]{64}$'))


def blank(column):
    return or_(column.is_(None), func.length(func.trim(column)) == 0)


def metadata_bad(model):
    return or_(~valid_hash(model.sha256), model.sha256.is_(None),
        model.tamano_bytes.is_(None), model.tamano_bytes < 0,
        blank(model.storage_key), blank(model.nombre_original), blank(model.mime_type))


def metadata_flags(model):
    return (case((or_(~valid_hash(model.sha256), model.sha256.is_(None)), 1), else_=0)
        + case((or_(model.tamano_bytes.is_(None), model.tamano_bytes < 0), 2), else_=0)
        + case((blank(model.storage_key), 4), else_=0)
        + case((blank(model.nombre_original), 8), else_=0)
        + case((blank(model.mime_type), 16), else_=0))


def visible_versions(user, audit_id=None):
    # Include only documents independently readable as well as versions.
    # DISTINCT establishes a materialization barrier for nested assignment scopes.
    # Independent derived tables avoid MySQL's shared CTE disk-spill bug #112704.
    docs = select(Documento.id).where(scopes.scope(user, 'documento', audit_id)).distinct().subquery('readable_docs')
    # For auditors/owners version_scope is precisely the parent's document_scope.
    # The scoped join already enforces it; repeating its nested EXISTS for every
    # row causes unnecessary correlated work. Approvers retain exact assignment.
    version_condition = authz.assigned_version(user, VersionDocumento.id) if user.rol == 'APROBADOR' else literal(True)
    return select(VersionDocumento.id, VersionDocumento.documento_id,
        VersionDocumento.numero_version, VersionDocumento.nombre_original,
        VersionDocumento.sha256, VersionDocumento.tamano_bytes, VersionDocumento.storage_key,
        VersionDocumento.mime_type, VersionDocumento.created_at).join(
            docs, docs.c.id == VersionDocumento.documento_id).where(
                version_condition).distinct().subquery('readable_versions')


def detection_query(user, filters, version_id=None):
    aid = filters.auditoria_id
    v = visible_versions(user, aid)
    c = v.c
    hash_key = func.lower(c.sha256)
    by_hash = dict(partition_by=hash_key)
    by_doc = dict(partition_by=c.documento_id, order_by=(c.numero_version, c.id))
    by_doc_hash = dict(partition_by=(c.documento_id, hash_key))
    # Storage/MIME/size are checked in the metadata branch, not in the windows.
    # Carrying them through every window sort needlessly inflates temporary rows.
    w = select(c.id, c.documento_id, c.numero_version, c.nombre_original, c.sha256, c.created_at,
        func.min(c.documento_id).over(**by_hash).label('first_doc'),
        func.max(c.documento_id).over(**by_hash).label('last_doc'),
        func.first_value(c.id).over(**by_hash, order_by=(c.documento_id, c.id)).label('first_id'),
        func.first_value(c.id).over(**by_hash, order_by=(c.documento_id.desc(), c.id.desc())).label('last_id'),
        func.min(c.id).over(**by_doc_hash).label('same_first'),
        func.max(c.id).over(**by_doc_hash).label('same_last'),
        func.count().over(partition_by=(c.documento_id, c.numero_version)).label('number_count'),
        func.lag(c.id).over(**by_doc).label('prev_id'),
        func.lag(c.numero_version).over(**by_doc).label('prev_number'),
        func.lag(hash_key).over(**by_doc).label('prev_hash'),
        func.lag(c.created_at).over(**by_doc).label('prev_date')).subquery('version_windows')
    a = w.c
    statements = []

    def projection(source, kind, severity, resource, rid, docid, name, condition,
                   related_id=None, related_doc=None, flags=None):
        statements.append(select(literal(kind).label('tipo'), literal(severity).label('severidad'),
            literal(resource).label('recurso'), rid.label('recurso_id'), docid.label('documento_id'),
            name.label('nombre'), (related_id if related_id is not None else literal(None)).label('related_id'),
            (related_doc if related_doc is not None else literal(None)).label('related_doc'),
            (flags if flags is not None else literal(0)).label('metadata_flags'))
            .select_from(source).where(condition))

    peer = case((a.documento_id != a.first_doc, a.first_id), else_=a.last_id)
    peer_doc = case((a.documento_id != a.first_doc, a.first_doc), else_=a.last_doc)
    adjacent = a.prev_number == a.numero_version - 1
    # Expand five rules from one window pass. Repeating the derived window table
    # in UNION branches would recompute every sort five times after avoiding CTEs.
    kinds = ('DUPLICATE_HASH', 'HASH_REPETIDO', 'VERSION_SIN_CAMBIO',
             'SECUENCIA_TEMPORAL', 'NUMERO_VERSION_DUPLICADO')
    rules = union_all(*(select(literal(i).label('rule')) for i in range(5))).subquery('window_rules')
    rule = rules.c.rule
    conditions = (
        and_(valid_hash(a.sha256), a.first_doc != a.last_doc),
        and_(valid_hash(a.sha256), a.same_first != a.same_last),
        and_(adjacent, valid_hash(a.sha256), func.lower(a.sha256) == a.prev_hash),
        and_(adjacent, a.created_at < a.prev_date), a.number_count > 1)
    statements.append(select(
        case(*((rule == i, kind) for i, kind in enumerate(kinds))).label('tipo'),
        case((rule < 3, 'INFO'), else_='WARNING').label('severidad'),
        literal('version').label('recurso'), a.id.label('recurso_id'),
        a.documento_id.label('documento_id'), a.nombre_original.label('nombre'),
        case((rule == 0, peer),
             (rule == 1, case((a.id != a.same_first, a.same_first), else_=a.same_last)),
             (rule.in_((2, 3)), a.prev_id)).label('related_id'),
        case((rule == 0, peer_doc), (rule.in_((1, 2, 3)), a.documento_id)).label('related_doc'),
        literal(0).label('metadata_flags')).select_from(w.join(rules, literal(True)))
        .where(or_(*(and_(rule == i, condition) for i, condition in enumerate(conditions)))))
    projection(v, 'METADATA_INCOMPLETA', 'WARNING', 'version', c.id, c.documento_id,
        c.nombre_original, metadata_bad(c), flags=metadata_flags(c))

    d = select(Documento.id, Documento.titulo, Documento.estado, Documento.version_vigente_id).where(
        scopes.scope(user, 'documento', aid)).distinct().subquery('analysis_documents')
    dc = d.c
    # Correlated checks use the base table's indexes instead of rematerializing
    # all visible versions for each document/evidence row. Keep both scopes and
    # the parent-existence rule of visible_versions, including approver scope.
    version_visible = and_(scopes.scope(user, 'version', aid), exists(
        select(Documento.id).where(Documento.id == VersionDocumento.documento_id,
            scopes.scope(user, 'documento', aid)).correlate_except(Documento)))
    def visible_exists(*conditions):
        return exists(select(VersionDocumento.id).where(version_visible, *conditions)
                      .correlate_except(VersionDocumento))
    has_version = visible_exists(VersionDocumento.documento_id == dc.id)
    projection(d, 'DOCUMENTO_SIN_VERSION', 'INFO', 'documento', dc.id, dc.id, dc.titulo,
        and_(literal(user.rol != 'APROBADOR'), ~has_version))
    projection(d, 'METADATA_INCOMPLETA', 'WARNING', 'documento', dc.id, dc.id, dc.titulo, blank(dc.titulo), flags=literal(32))
    projection(d, 'ESTADO_DESCONOCIDO', 'INFO', 'documento', dc.id, dc.id, dc.titulo,
        ~scopes.canonical_text(dc.estado).in_(('DRAFT', 'ACTIVE', 'ARCHIVED', 'OBSOLETE')))
    # Never inspect an inaccessible current version, even to signal its existence.
    # A version outside an audit filter is not a missing DB reference. Only
    # ADMIN may evaluate absence, across its full existing version read scope.
    missing_current = and_(dc.version_vigente_id.is_not(None), ~exists(
        select(VersionDocumento.id).where(VersionDocumento.id == dc.version_vigente_id,
            authz.version_scope(user)))) if user.rol == 'ADMIN' else false()
    mismatch = or_(visible_exists(VersionDocumento.id == dc.version_vigente_id,
                                 VersionDocumento.documento_id != dc.id),
        missing_current)
    projection(d, 'VERSION_VIGENTE_INCONGRUENTE', 'WARNING', 'documento', dc.id, dc.id, dc.titulo, mismatch)

    e = select(Evidencia.id, Evidencia.titulo, Evidencia.tipo, Evidencia.documento_id,
        Evidencia.version_documento_id, Evidencia.auditoria_id, Evidencia.storage_key,
        Evidencia.sha256, Evidencia.nombre_original, Evidencia.mime_type, Evidencia.tamano_bytes).where(
        scopes.scope(user, 'evidencia', aid)).distinct().subquery('analysis_evidence')
    ec = e.c
    projection(e, 'METADATA_INCOMPLETA', 'WARNING', 'evidencia', ec.id, ec.documento_id,
        ec.titulo, and_(scopes.canonical_text(ec.tipo) == 'FILE', metadata_bad(ec)), flags=metadata_flags(ec))
    projection(e, 'ESTADO_DESCONOCIDO', 'INFO', 'evidencia', ec.id, ec.documento_id, ec.titulo,
        ~scopes.canonical_text(ec.tipo).in_(scopes.EVIDENCE_TYPES))
    projection(e, 'RELACION_INCONGRUENTE', 'WARNING', 'evidencia', ec.id, ec.documento_id,
        ec.titulo, or_(visible_exists(VersionDocumento.id == ec.version_documento_id,
            or_(ec.documento_id.is_(None), VersionDocumento.documento_id != ec.documento_id)),
            and_(literal(user.rol == 'ADMIN'), exists(select(Evidencia.id).where(
                Evidencia.id == ec.id, scopes.scope(user, 'evidencia', aid), ~authz.evidence_consistency())))))
    # Both endpoints must be visible before comparison. No arbitrary evidence requirement.
    h = select(Hallazgo.id, Hallazgo.titulo, Hallazgo.auditoria_id).where(
        scopes.scope(user, 'hallazgo', aid)).distinct().subquery('analysis_findings')
    incompatible = exists(select(ec.id).join(HallazgoEvidencia,
        HallazgoEvidencia.evidencia_id == ec.id).where(
        HallazgoEvidencia.hallazgo_id == h.c.id, ec.auditoria_id != h.c.auditoria_id))
    projection(h, 'RELACION_INCONGRUENTE', 'WARNING', 'hallazgo', h.c.id, literal(None),
        h.c.titulo, incompatible)
    pivot_bad = exists(select(DocumentoAuditoria.id).join(Auditoria,
        Auditoria.id == DocumentoAuditoria.auditoria_id).join(VersionDocumento,
        VersionDocumento.id == DocumentoAuditoria.version_documento_id).where(
        DocumentoAuditoria.documento_id == dc.id, VersionDocumento.documento_id != dc.id, version_visible,
        scopes.scope(user, 'auditoria', aid)))
    projection(d, 'RELACION_INCONGRUENTE', 'WARNING', 'documento', dc.id, dc.id, dc.titulo, pivot_bad)

    derived = union_all(*statements).subquery('derived_analysis')
    stmt = select(derived)
    if filters.documento_id is not None:
        stmt = stmt.where(derived.c.documento_id == filters.documento_id)
    if version_id is not None:
        stmt = stmt.where(derived.c.recurso == 'version', derived.c.recurso_id == version_id)
    if getattr(filters, 'tipo', None) is not None:
        stmt = stmt.where(derived.c.tipo == filters.tipo)
    if getattr(filters, 'severidad', None) is not None:
        stmt = stmt.where(derived.c.severidad == filters.severidad)
    return stmt


def visibility_query(user):
    """Stream a minimal scope fingerprint; no metadata/hashes or global aggregates."""
    branches = []
    for resource in ('auditoria', 'documento', 'version', 'evidencia', 'hallazgo', 'aprobacion'):
        model = scopes.RESOURCES[resource][0]
        branches.append(select(literal(resource).label('resource'), model.id.label('id')).where(
            scopes.scope(user, resource)))
    rows = union_all(*branches).subquery('scope_identity')
    return select(rows).order_by(rows.c.resource, rows.c.id)
