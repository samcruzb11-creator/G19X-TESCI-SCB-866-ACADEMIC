"""Explainable read projections with a fresh, read-only authorization barrier."""
from datetime import datetime, timezone
import hashlib
from fastapi import HTTPException
from sqlalchemy import select, func, case
from sqlalchemy.orm import Session
from app.models.entities import Documento, VersionDocumento, Usuario
from app.models.auth import AuthSession
from app.schemas.analisis import (Detection, DetectionPage, AnalysisSummary, ResourceAnalysis)
from app.services import analisis_queries as queries
from app.services import analisis_rules as rules
from app.services import authorization_service as authz
from app.services.dashboard_service import validate_context
from app.services.storage_service import storage_service

TEXT = {
    'DUPLICATE_HASH': ('posible duplicado', 'Coincidencia binaria entre documentos',
        'Esta versión tiene el mismo SHA-256 válido que otra versión de un documento autorizado distinto.',
        'SHA-256 válido e idéntico; documentos distintos'),
    'HASH_REPETIDO': ('señal', 'Contenido repetido en el documento',
        'Dos versiones autorizadas del mismo documento tienen contenido binario idéntico según el SHA-256 registrado.',
        'SHA-256 válido e idéntico; versiones distintas del mismo documento'),
    'VERSION_SIN_CAMBIO': ('señal', 'Versión consecutiva sin cambio binario',
        'Las versiones N y N+1 autorizadas tienen contenido binario idéntico según el SHA-256 registrado.',
        'N+1 consecutivo y SHA-256 válido idéntico'),
    'SECUENCIA_TEMPORAL': ('inconsistencia objetiva', 'Orden temporal incoherente',
        'La versión N+1 tiene una fecha de creación anterior a la versión N autorizada.',
        'numero_version consecutivo y created_at decreciente'),
    'NUMERO_VERSION_DUPLICADO': ('inconsistencia objetiva', 'Número de versión repetido',
        'Hay varias versiones autorizadas del mismo documento con el mismo número.',
        'COUNT por documento y numero_version mayor que uno'),
    'METADATA_INCOMPLETA': ('inconsistencia objetiva', 'Metadatos estructurales incompletos',
        'Hay campos requeridos vacíos, un SHA-256 inválido o un tamaño ausente/negativo. Un tamaño cero es válido.',
        'título vacío o campos FILE: nombre, MIME, storage_key, SHA-256 hexadecimal de 64 caracteres y tamaño >= 0'),
    'DOCUMENTO_SIN_VERSION': ('señal', 'Documento existente sin versiones',
        'El documento existe y no tiene ninguna versión registrada dentro del alcance completo de lectura del documento.',
        'NOT EXISTS versión autorizada; excluye alcance parcial de APROBADOR'),
    'VERSION_VIGENTE_INCONGRUENTE': ('inconsistencia objetiva', 'Versión vigente incongruente',
        'La referencia vigente pertenece a otro documento autorizado o, para ADMIN con alcance completo, no existe.',
        'version_vigente.documento_id diferente al documento; ausencia solo con alcance completo ADMIN'),
    'RELACION_INCONGRUENTE': ('inconsistencia objetiva', 'Relación documental incongruente',
        'Los recursos autorizados de esta relación tienen documentos o contextos de auditoría incompatibles.',
        'Comparación de documento_id o auditoria_id entre ambos extremos visibles'),
    'ESTADO_DESCONOCIDO': ('anomalía', 'Estado o tipo no reconocido',
        'El valor registrado no coincide exactamente con los valores documentados del dominio.',
        'Whitelist exacta y binaria de estado/tipo; sin interpretar el valor desconocido'),
    'POSIBLE_DUPLICADO': ('posible duplicado', 'Nombres potencialmente duplicados',
        'Dos versiones autorizadas de documentos distintos tienen nombres similares, igual extensión y tamaño registrado. Requiere revisión humana.',
        'NFKC/casefold/puntuación/espacios; token común; extensión y tamaño iguales; SequenceMatcher >= threshold'),
    'ARCHIVO_NO_DISPONIBLE': ('anomalía', 'Archivo no disponible al consultar',
        'No se pudo comprobar un archivo regular en la ruta administrada. Puede estar ausente o temporalmente inaccesible.',
        'Stat de ruta autorizada dentro del storage; sin abrir contenido'),
    'RUTA_NO_SEGURA': ('inconsistencia objetiva', 'Referencia de almacenamiento no segura',
        'La referencia no cumple las reglas de rutas administradas o contiene un enlace. No se inspeccionó su destino.',
        'Solo documents/evidence; sin traversal, absolutos, UNC, codificación porcentual ni symlinks/junctions'),
}


def detection(row, stamp, similarity=None, threshold=None):
    kind = row['tipo']
    classification, title, explanation, technical = TEXT[kind]
    version = row['recurso'] == 'version'
    target = dict(pagina='documento' if version else row['recurso'],
        id=row['documento_id'] if version else row['recurso_id'],
        version_id=row['recurso_id'] if version else None)
    related = None
    if row.get('related_id') is not None:
        related = dict(pagina='documento', id=row['related_doc'], version_id=row['related_id'])
    evidence = [technical]
    for bit, field in ((1,'SHA-256 ausente o inválido'), (2,'Tamaño ausente o negativo'),
        (4,'Referencia de storage vacía'), (8,'Nombre original vacío'), (16,'MIME vacío'), (32,'Título vacío')):
        if (row.get('metadata_flags') or 0) & bit:
            evidence.append(field)
    if similarity is not None:
        evidence += [f'similitud_nombre={similarity!r}', f'threshold={threshold!r}']
    return Detection(tipo=kind, clasificacion=classification, severidad=row['severidad'],
        recurso=row['recurso'], recurso_id=row['recurso_id'], nombre=row['nombre'] or '',
        titulo=title, explicacion=explanation, evidencia_tecnica=evidence,
        regla=f'7E:{kind}:1', evaluado_en=stamp, destino=target, relacionado=related,
        similitud_nombre=similarity)


def validate(db, user, filters, version_id=None):
    validate_context(db, user, filters)
    if filters.documento_id is not None:
        if db.scalar(select(Documento.id).where(Documento.id == filters.documento_id,
            queries.scopes.scope(user, 'documento', filters.auditoria_id))) is None:
            raise HTTPException(404, 'Recurso no encontrado')
    if version_id is not None:
        v = queries.visible_versions(user, filters.auditoria_id)
        if db.scalar(select(v.c.id).where(v.c.id == version_id,
            *([v.c.documento_id == filters.documento_id] if filters.documento_id is not None else []))) is None:
            raise HTTPException(404, 'Recurso no encontrado')


def visibility_digest(db, user):
    digest = hashlib.sha256(f'{user.id}:{user.rol}:{user.activo}'.encode())
    for resource, rid in db.execute(queries.visibility_query(user).execution_options(yield_per=200)):
        digest.update(f'|{resource}:{rid}'.encode())
    return digest.digest()


def fresh_authorization(db, user, expected):
    """New transaction sees committed revocations even under REPEATABLE READ.

    It never refreshes the request snapshot with business data. A changed scope
    discards the entire response. Authorization is linearized at this barrier;
    a later revocation affects the next request, as with any authorized read.
    """
    # All projections have already been materialized from the original snapshot.
    # Keep only immutable identity values before rollback expires ORM attributes.
    # Return the first connection before borrowing one for the fresh barrier:
    # otherwise concurrent readers can hold every slot while waiting for another.
    user_id, role = user.id, user.rol
    session_ids = [r.sid for r in db.identity_map.values() if isinstance(r, AuthSession)]
    bind = db.get_bind()
    if db.new or db.dirty or db.deleted:
        raise RuntimeError('Analysis requires a read-only request transaction')
    db.rollback()
    with Session(bind, autoflush=False) as fresh:
        if fresh.get_bind().dialect.name == 'mysql':
            fresh.connection().exec_driver_sql('SET TRANSACTION READ ONLY')
        actor = fresh.get(Usuario, user_id)
        if actor is None or not actor.activo or actor.rol != role:
            raise HTTPException(403, 'Operacion no permitida')
        for sid in session_ids:
            current = fresh.get(AuthSession, sid)
            if (current is None or current.revoked_at is not None
                    or current.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None)):
                raise HTTPException(401, 'Credenciales invalidas o sesion no vigente')
        if visibility_digest(fresh, actor) != expected:
            raise HTTPException(409, 'El alcance cambio durante la consulta; vuelva a consultar')


def summary(db, user, context, stamp):
    stmt = queries.detection_query(user, context).subquery()
    counts = db.execute(select(stmt.c.tipo, stmt.c.severidad, func.count()).group_by(
        stmt.c.tipo, stmt.c.severidad)).all()
    types = {}
    severity = dict(INFO=0, WARNING=0)
    for kind, level, count in counts:
        types[kind] = types.get(kind, 0) + count
        severity[level] += count
    return AnalysisSummary(evaluado_en=stamp, total=sum(types.values()),
        por_tipo=types, por_severidad=severity)


def page(db, user, filters, stamp, version_id=None):
    stmt = queries.detection_query(user, filters, version_id)
    cols = stmt.selected_columns
    # Compute the total before LIMIT in the same scan as the page. Repeating all
    # window detections for COUNT doubles the most expensive endpoint under load.
    rows = db.execute(stmt.add_columns(func.count().over().label('page_total'))
        .order_by(case((cols.severidad == 'WARNING', 0), else_=1),
        cols.tipo, cols.recurso, cols.recurso_id).limit(filters.limit).offset(filters.offset)).mappings().all()
    total = rows[0]['page_total'] if rows else (
        db.scalar(select(func.count()).select_from(stmt.subquery())) if filters.offset else 0)
    return DetectionPage(total=total, limit=filters.limit, offset=filters.offset,
        items=[detection(dict(r), stamp) for r in rows])


def detail(db, user, filters, stamp, version_id=None, policy=rules.POLICY):
    anomalies = page(db, user, filters, stamp, version_id)
    v = queries.visible_versions(user, filters.auditoria_id)
    conditions = [v.c.id == version_id] if version_id is not None else [v.c.documento_id == filters.documento_id]
    versions = db.execute(select(v).where(*conditions).order_by(v.c.numero_version.desc(), v.c.id.desc())
        .limit(policy.versions_limit + 1)).mappings().all()
    complete = len(versions) <= policy.versions_limit
    versions = versions[:policy.versions_limit]
    local = []
    def permitted_kind(kind):
        return ((filters.tipo is None or filters.tipo == kind)
                and (filters.severidad is None or filters.severidad == ('INFO' if kind == 'POSIBLE_DUPLICADO' else 'WARNING')))
    for row in versions:
        status = rules.storage_status(storage_service, row['storage_key'])
        if status is not None and permitted_kind(status):
            local.append(detection(dict(tipo=status, severidad='WARNING', recurso='version',
                recurso_id=row['id'], documento_id=row['documento_id'], nombre=row['nombre_original']), stamp))
    candidates = []
    truncated = False
    # Only the latest readable version is a name-comparison anchor. This avoids
    # queries per version and bounds SequenceMatcher work to <= 64 pairs/request.
    if versions and permitted_kind('POSIBLE_DUPLICADO'):
        anchor = versions[0]
        if rules.valid_hash(anchor['sha256']) and anchor['tamano_bytes'] is not None:
            _, extension = rules.name_parts(anchor['nombre_original'])
            if extension:
                candidates = db.execute(select(v).where(v.c.documento_id != anchor['documento_id'],
                    v.c.tamano_bytes == anchor['tamano_bytes'], queries.valid_hash(v.c.sha256),
                    func.lower(v.c.sha256) != anchor['sha256'].lower(),
                    func.lower(v.c.nombre_original).endswith(extension, autoescape=True))
                    .order_by(v.c.id).limit(policy.candidates_limit + 1)).mappings().all()
                truncated = len(candidates) > policy.candidates_limit
                candidates = candidates[:policy.candidates_limit]
                for candidate in candidates:
                    value = rules.similarity(anchor['nombre_original'], candidate['nombre_original'], policy)
                    if value is not None:
                        local.append(detection(dict(tipo='POSIBLE_DUPLICADO', severidad='INFO', recurso='version',
                            recurso_id=anchor['id'], documento_id=anchor['documento_id'], nombre=anchor['nombre_original'],
                            related_id=candidate['id'], related_doc=candidate['documento_id']), stamp, value,
                            policy.similarity_threshold))
    return ResourceAnalysis(evaluado_en=stamp, anomalias=anomalies, comprobaciones_locales=local,
        versiones_comprobadas=len(versions), versiones_comprobadas_limite=policy.versions_limit,
        comprobacion_completa=complete, candidatos_comparados=len(candidates),
        candidatos_limite=policy.candidates_limit, candidatos_truncados=truncated)
