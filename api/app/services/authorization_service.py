"""Deny-by-default authorization, expressed as reusable SQL scopes."""
from fastapi import HTTPException
from sqlalchemy import select, exists, true, false, and_, or_
from app.models.entities import (Auditoria, Documento, DocumentoAuditoria, VersionDocumento,
                                Evidencia, RondaAprobacion, DecisionAprobacion, Usuario)

AUDITORES = {'AUDITOR_INTERNO', 'AUDITOR_EXTERNO'}
PERMISSIONS = {
    'auditoria.read': AUDITORES, 'auditoria.create': {'AUDITOR_INTERNO'},
    'documento.read': AUDITORES | {'RESPONSABLE_AREA', 'APROBADOR'},
    'documento.create': {'RESPONSABLE_AREA'}, 'documento.update': {'RESPONSABLE_AREA'},
    'version.read': AUDITORES | {'RESPONSABLE_AREA', 'APROBADOR'},
    'version.create': {'RESPONSABLE_AREA'},
    'evidencia.read': AUDITORES, 'evidencia.create': AUDITORES,
    'historial.read': set(), 'usuarios.read': {'AUDITOR_INTERNO'},
    'areas.read': AUDITORES | {'RESPONSABLE_AREA', 'APROBADOR'},
}

def require_permission(user: Usuario, action: str) -> None:
    if action not in PERMISSIONS or (user.rol != 'ADMIN' and user.rol not in PERMISSIONS[action]):
        raise HTTPException(403, 'Operacion no permitida')

def auditoria_scope(user: Usuario):
    if user.rol == 'ADMIN':
        return true()
    return Auditoria.responsable_id == user.id if user.rol in AUDITORES else false()

def linked_document(document_id, audit_id):
    return exists(select(DocumentoAuditoria.id).where(
        DocumentoAuditoria.documento_id == document_id,
        DocumentoAuditoria.auditoria_id == audit_id).correlate_except(DocumentoAuditoria))

def assigned_version(user, version_id):
    return exists(select(DecisionAprobacion.id).join(RondaAprobacion,
        DecisionAprobacion.ronda_aprobacion_id == RondaAprobacion.id).where(
        DecisionAprobacion.aprobador_id == user.id,
        RondaAprobacion.version_documento_id == version_id).correlate_except(DecisionAprobacion, RondaAprobacion))

def documento_scope(user: Usuario):
    if user.rol == 'ADMIN':
        return true()
    if user.rol == 'RESPONSABLE_AREA':
        return Documento.responsable_id == user.id
    if user.rol in AUDITORES:
        return exists(select(DocumentoAuditoria.id).join(Auditoria,
            DocumentoAuditoria.auditoria_id == Auditoria.id).where(
            DocumentoAuditoria.documento_id == Documento.id, auditoria_scope(user)).correlate_except(DocumentoAuditoria, Auditoria))
    if user.rol == 'APROBADOR':
        return exists(select(VersionDocumento.id).where(
            VersionDocumento.documento_id == Documento.id, assigned_version(user, VersionDocumento.id)).correlate_except(VersionDocumento))
    return false()

def version_scope(user: Usuario):
    if user.rol == 'ADMIN':
        return true()
    if user.rol == 'APROBADOR':
        return assigned_version(user, VersionDocumento.id)
    if user.rol in AUDITORES | {'RESPONSABLE_AREA'}:
        return exists(select(Documento.id).where(
            Documento.id == VersionDocumento.documento_id,
            documento_scope(user)).correlate_except(Documento))
    return false()

def evidencia_scope(user: Usuario):
    if user.rol == 'ADMIN':
        return true()
    if user.rol not in AUDITORES:
        return false()
    return and_(exists(select(Auditoria.id).where(Auditoria.id == Evidencia.auditoria_id, auditoria_scope(user))),
        or_(Evidencia.documento_id.is_(None), linked_document(Evidencia.documento_id, Evidencia.auditoria_id)),
        or_(Evidencia.version_documento_id.is_(None), exists(select(VersionDocumento.id).where(
            VersionDocumento.id == Evidencia.version_documento_id,
            VersionDocumento.documento_id == Evidencia.documento_id,
            linked_document(VersionDocumento.documento_id, Evidencia.auditoria_id)))))

def resource(db, user, model, resource_id, action, scope, *conditions):
    require_permission(user, action)
    row = db.scalar(select(model).where(model.id == resource_id, scope(user), *conditions))
    if row is None:
        raise HTTPException(404, 'Recurso no encontrado')
    return row

def authorize_document_create(user, payload):
    require_permission(user, 'documento.create')
    if user.rol != 'ADMIN' and payload.responsable_id != user.id:
        raise HTTPException(403, 'Debe asignarse como responsable')

def authorize_document_update(user, document, payload):
    require_permission(user, 'documento.update')
    if user.rol != 'ADMIN' and document.responsable_id != user.id:
        raise HTTPException(404, 'Recurso no encontrado')
    if user.rol != 'ADMIN' and 'responsable_id' in payload.model_fields_set and payload.responsable_id != user.id:
        raise HTTPException(403, 'Reasignacion reservada a ADMIN')

def eligible_users_scope():
    return and_(Usuario.activo.is_(True), Usuario.rol.in_(AUDITORES))

def authorize_audit_create(db, user, payload):
    require_permission(user, 'auditoria.create')
    if user.rol != 'ADMIN' and payload.responsable_id != user.id:
        raise HTTPException(403, 'Debe asignarse como responsable')
    if db.scalar(select(Usuario.id).where(Usuario.id == payload.responsable_id, eligible_users_scope())) is None:
        raise HTTPException(404, 'Responsable elegible no encontrado')

def authorize_evidence_references(db, user, audit_id, document_id, version_id):
    require_permission(user, 'evidencia.create')
    audit = db.get(Auditoria, audit_id)
    if audit is None or (user.rol != 'ADMIN' and audit.responsable_id != user.id):
        raise HTTPException(404, 'Recurso no encontrado')
    if version_id is not None:
        version = db.get(VersionDocumento, version_id)
        if version is None or (document_id is not None and version.documento_id != document_id):
            raise HTTPException(404, 'Recurso no encontrado')
        document_id = version.documento_id
    if document_id is not None and db.scalar(select(Documento.id).where(
        Documento.id == document_id, linked_document(Documento.id, audit_id))) is None:
        raise HTTPException(404, 'Recurso no encontrado')
    return document_id


def authorize_version_create(user, document):
    require_permission(user, 'version.create')
    if user.rol != 'ADMIN' and document.responsable_id != user.id:
        raise HTTPException(404, 'Recurso no encontrado')


def usuarios_scope(user):
    return true() if user.rol == 'ADMIN' else eligible_users_scope()


def sanitize_document_metadata(user, data):
    """Do not disclose the ID of a current version absent from the scoped load."""
    if user.rol == 'APROBADOR' and data.version_vigente is None:
        data.version_vigente_id = None
    return data
