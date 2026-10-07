"""Adversarial 7E contracts, also imported into protected real MySQL tests."""
from datetime import datetime, timedelta
from io import BytesIO
import json
import math
from pathlib import Path
import pytest
from pydantic import ValidationError
from sqlalchemy import select, event
from tests_unit.test_rbac_unit import rbac
from tests_unit.test_aprobacion_unit import approvals
from app.models.entities import (Usuario, Documento, VersionDocumento, Auditoria,
    DocumentoAuditoria, Evidencia, Hallazgo, HallazgoEvidencia)
from app.schemas.analisis import AnalysisFilters, AnalysisContext
from app.services import analisis_service as service, analisis_rules as rules

ENDPOINTS = ('resumen','anomalias','documentos/1','versiones/1')


@pytest.fixture
def analysis(approvals, monkeypatch):
    c, db, actor, storage = approvals
    monkeypatch.setattr(service, 'storage_service', storage)
    return approvals


def get(c, endpoint='anomalias', **params):
    response = c.get('/api/v1/analisis/'+endpoint, params=params)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    return response.json()


def stable(value):
    if isinstance(value, dict):
        return {k:stable(v) for k,v in value.items() if k != 'evaluado_en'}
    if isinstance(value, list):return [stable(v) for v in value]
    return value


def kinds(page):
    return {r['tipo'] for r in page['items']}


def test_hash_duplicates_windows_no_self_no_pair_explosion_privacy(analysis):
    c, db, actor, storage = analysis
    data = get(c,limit=100)
    assert sum(r['tipo']=='DUPLICATE_HASH' for r in data['items']) == 5
    assert sum(r['tipo']=='HASH_REPETIDO' for r in data['items']) == 2
    assert sum(r['tipo']=='VERSION_SIN_CAMBIO' for r in data['items']) == 1
    for r in data['items']:
        assert r['explicacion'] and r['regla'] and r['evidencia_tecnica']
        if r['relacionado']:
            assert r['relacionado']['version_id'] != r['recurso_id']
    serialized=json.dumps(data)
    assert db.get(VersionDocumento,1).sha256 not in serialized
    assert 'sha256' not in serialized and 'storage_key' not in serialized
    assert str(storage.base_path) not in serialized
    for version in db.scalars(select(VersionDocumento)):
        version.sha256=f'{version.id:064x}'
    db.commit()
    assert kinds(get(c,limit=100)).isdisjoint({'DUPLICATE_HASH','HASH_REPETIDO','VERSION_SIN_CAMBIO'})


@pytest.mark.parametrize('actor',[2,3,4,5,6,7,8])
def test_duplicate_leakage_hidden_hash_name_size_counts_flags_pages(analysis,actor):
    c, db, user, _ = analysis;user['id']=actor
    endpoints=['resumen','anomalias']
    allowed=db.scalar(select(VersionDocumento.id).where(service.queries.scopes.scope(db.get(Usuario,actor),'version')))
    if allowed is not None:endpoints += [f'versiones/{allowed}']
    baseline={e:stable(get(c,e)) for e in endpoints}
    db.add(Documento(id=999,codigo='SECRET',titulo='SECRET <script>',tipo='TEST',estado='ACTIVE',
        area_id=1,responsable_id=1,created_by_id=1));db.flush()
    db.add(VersionDocumento(id=999,documento_id=999,numero_version=1,
        storage_key='documents/secret.txt',nombre_original='SECRET.txt',mime_type='text/plain',
        tamano_bytes=7,sha256=db.get(VersionDocumento,1).sha256,subido_por_id=1));db.commit()
    for endpoint in endpoints:
        data=get(c,endpoint)
        assert stable(data)==baseline[endpoint]
        assert 'SECRET' not in json.dumps(stable(data)) and '999' not in json.dumps(stable(data))
    assert c.get('/api/v1/analisis/documentos/999').status_code==404
    assert c.get('/api/v1/analisis/versiones/999').status_code==404


@pytest.mark.parametrize('actor,allowed,denied',[(2,1,2),(3,3,1),(4,1,2),(5,1,2),(8,2,1)])
def test_idor_roles_documents_versions_audits(analysis,actor,allowed,denied):
    c,db,user,_=analysis;user['id']=actor
    assert c.get(f'/api/v1/analisis/documentos/{allowed}').status_code==200
    a=c.get(f'/api/v1/analisis/documentos/{denied}')
    b=c.get('/api/v1/analisis/documentos/100000')
    assert a.status_code==b.status_code==404 and a.json()==b.json()
    if actor==5:
        assert c.get('/api/v1/analisis/versiones/2').status_code==404
        assert kinds(get(c,'documentos/1')['anomalias']).isdisjoint({'HASH_REPETIDO','VERSION_SIN_CAMBIO','DOCUMENTO_SIN_VERSION'})
    if actor in (4,5,8):
        for audit in (1,999):assert c.get('/api/v1/analisis/resumen',params={'auditoria_id':audit}).status_code==403
    elif actor==2:
        for audit in (2,999):assert c.get('/api/v1/analisis/resumen',params={'auditoria_id':audit}).status_code==404


def test_unknown_role_fail_closed_without_new_permission(analysis):
    c,db,user,_=analysis
    db.get(Usuario,1).rol='CONSULTA' # in-memory legacy identity, no write
    for endpoint in ENDPOINTS:assert c.get('/api/v1/analisis/'+endpoint).status_code==403
    db.rollback()


@pytest.mark.parametrize('endpoint',ENDPOINTS)
@pytest.mark.parametrize('field,value',[('auditoria_id','0'),('documento_id','-1'),('documento_id','true'),
    ('documento_id','1.0'),('documento_id','1e0'),('documento_id','١'),('documento_id','1 OR 1=1'),
    ('documento_id','18446744073709551616'),('limit','101'),('limit','0'),('limit','1.0'),
    ('offset','10001'),('offset','-1'),('tipo',"x' UNION SELECT 1"),('severidad','CRITICAL'),
    ('sort','id;DROP TABLE documentos'),('rol','ADMIN'),('q',"' OR 1=1 --")])
def test_sqli_strict_whitelist_pagination_ids(analysis,endpoint,field,value):
    c,_,_,_=analysis
    assert c.get('/api/v1/analisis/'+endpoint,params={field:value}).status_code==422


@pytest.mark.parametrize('value',[True,False,1.0,'1e0',0,-1,2**64])
def test_pydantic_exact_ids(value):
    for model in (AnalysisContext,AnalysisFilters):
        with pytest.raises(ValidationError):model(documento_id=value)


@pytest.mark.parametrize('value',['0','-1','true','1.0','1e0','١','1 OR 1=1','18446744073709551616'])
def test_strict_path_ids(analysis,value):
    c,_,_,_=analysis
    for resource in ('documentos','versiones'):
        assert c.get('/api/v1/analisis/'+resource+'/'+value).status_code==422


def test_summary_denominators_deterministic_sql_pagination(analysis):
    c,db,user,_=analysis
    full=get(c,limit=100)
    summary=get(c,'resumen')
    assert full['total']==summary['total']==sum(summary['por_tipo'].values())==sum(summary['por_severidad'].values())
    pages=[]
    for offset in range(full['total']):pages += get(c,limit=1,offset=offset)['items']
    assert stable(pages)==stable(full['items'])
    assert get(c,offset=10000)['items']==[]
    for level in ('INFO','WARNING'):
        assert all(r['severidad']==level for r in get(c,severidad=level)['items'])
    db.add(Usuario(id=9,nombre='Empty',correo='empty@example.invalid',correo_normalizado='empty@example.invalid',
        password_hash='unused',rol='AUDITOR_INTERNO',activo=True));db.commit();user['id']=9
    assert get(c,'resumen')['total']==0 and get(c)['items']==[]


def test_partial_scope_no_invented_missing_versions_no_gap_rule(analysis):
    c,db,user,_=analysis
    db.get(VersionDocumento,2).numero_version=7
    db.commit()
    assert 'VERSION_SIN_CAMBIO' not in kinds(get(c,limit=100))
    assert 'SECUENCIA_TEMPORAL' not in kinds(get(c,limit=100))
    db.add(Documento(id=5,codigo='EMPTY',titulo='Empty',tipo='TEST',estado='ARCHIVED',area_id=1,
        responsable_id=4,created_by_id=1));db.commit()
    assert 'DOCUMENTO_SIN_VERSION' in kinds(get(c,documento_id=5))
    user['id']=5
    assert c.get('/api/v1/analisis/documentos/5').status_code==404


def test_objective_metadata_time_and_visible_current_version_mismatch(analysis):
    c,db,user,_=analysis
    db.get(VersionDocumento,2).created_at=db.get(VersionDocumento,1).created_at-timedelta(seconds=1)
    db.get(VersionDocumento,3).sha256='g'*64
    db.get(VersionDocumento,3).nombre_original=' '
    db.get(Documento,1).version_vigente_id=3
    db.commit()
    assert {'SECUENCIA_TEMPORAL','METADATA_INCOMPLETA','VERSION_VIGENTE_INCONGRUENTE'} <= kinds(get(c,limit=100))
    user['id']=4
    assert 'VERSION_VIGENTE_INCONGRUENTE' not in kinds(get(c,documento_id=1))


def test_cross_audit_cross_document_links_require_both_visible(analysis):
    c,db,user,_=analysis
    db.add(Hallazgo(id=1,auditoria_id=1,numero=1,titulo='Finding',descripcion='TEST',
        categoria='TEST',severidad='LOW',created_by_id=1));db.flush()
    db.add(HallazgoEvidencia(hallazgo_id=1,evidencia_id=2,vinculada_por_id=1))
    db.get(Evidencia,1).version_documento_id=3
    db.get(DocumentoAuditoria,1).version_documento_id=2 # consistent; then corrupt document separately
    db.commit()
    data=get(c,limit=100,tipo='RELACION_INCONGRUENTE')
    assert {'evidencia','hallazgo'} <= {r['recurso'] for r in data['items']}
    user['id']=2
    assert not any(r['recurso']=='hallazgo' for r in get(c,tipo='RELACION_INCONGRUENTE')['items'])
    assert c.get('/api/v1/analisis/versiones/1',params={'documento_id':2}).status_code==404


@pytest.mark.parametrize('payload',['<script>alert(1)</script>','<img onerror=alert(1)>',
    '<svg onload=alert(1)>','quotes " \' & entities &lt;文档 🧪'])
def test_api_keeps_names_as_data_no_generated_urls_or_hashes(analysis,payload):
    c,db,user,_=analysis;db.get(VersionDocumento,1).nombre_original=payload;db.commit()
    data=get(c,'versiones/1')
    assert any(r['nombre']==payload for r in data['anomalias']['items'])
    for r in data['anomalias']['items']:assert r['destino']['pagina']=='documento'


@pytest.mark.parametrize('actor',[1,2,3,4,5,8])
def test_gets_readonly_constant_query_budget_no_lazy_loading(analysis,actor):
    c,db,user,_=analysis;user['id']=actor
    endpoints=['resumen','anomalias']
    if actor in (1,2,4,5):endpoints+=['documentos/1','versiones/1']
    for endpoint in endpoints:
        statements=[]
        def capture(conn,cursor,stmt,*args):statements.append(stmt.lstrip().upper())
        event.listen(db.get_bind(),'before_cursor_execute',capture)
        try:get(c,endpoint)
        finally:event.remove(db.get_bind(),'before_cursor_execute',capture)
        assert not any(s.startswith(('INSERT','UPDATE','DELETE','CREATE','ALTER','DROP')) for s in statements)
        assert sum(s.startswith(('SELECT','WITH')) for s in statements)<=10
    for method in ('post','patch','delete'):
        assert getattr(c,method)('/api/v1/analisis/resumen').status_code==405


def test_normalization_true_and_false_positive_threshold_symmetry():
    assert rules.normalized_name('Ｆactura-Enero.PDF')==rules.normalized_name('factura enero.pdf')
    for name in ('Factura Enero.pdf','factura enero.PDF','Factura-Enero.pdf'):
        assert rules.similarity(name,'Factura Enero.pdf')==1
    for left,right in [('Factura Enero.pdf','Factura Febrero.pdf'),('Factura 123.pdf','Factura 456.pdf'),
        ('Plan A.pdf','Plan B.pdf'),('Factura Enero.pdf','Factura Enero.txt'),('Informe financiero.pdf','Contrato laboral.pdf')]:
        assert rules.similarity(left,right) is None
    for left,right in [('Factura Enero 2026.pdf','Factura Enero 2027.pdf'),('Informe abc.pdf','Informe abcd.pdf')]:
        assert rules.similarity(left,right)==rules.similarity(right,left)
    t=rules.POLICY.similarity_threshold
    assert not rules.reaches_threshold(math.nextafter(t,0))
    assert rules.reaches_threshold(t) and rules.reaches_threshold(math.nextafter(t,1))
    with pytest.raises(ValueError):rules.LocalPolicy(similarity_threshold=0.1)
    # Real SequenceMatcher ratios below, exactly at, and above the default boundary.
    policy=rules.LocalPolicy(similarity_threshold=0.92)
    left='factura '+'a'*17+'.pdf'
    assert rules.similarity(left,'factura '+'a'*14+'bbb.pdf',policy) is None
    assert rules.similarity(left,'factura '+'a'*15+'bb.pdf',policy)==0.92
    assert rules.similarity(left,'factura '+'a'*16+'b.pdf',policy)==0.96


def test_hash_case_equivalence_and_invalid_hex_are_not_duplicate_keys(analysis):
    c,db,user,_=analysis
    before=stable(get(c,'versiones/1'))
    db.get(VersionDocumento,1).sha256=db.get(VersionDocumento,1).sha256.upper();db.commit()
    assert stable(get(c,'versiones/1'))==before
    db.get(VersionDocumento,1).sha256='invalid-hex';db.commit()
    assert 'DUPLICATE_HASH' not in kinds(get(c,'versiones/1')['anomalias'])
    assert 'METADATA_INCOMPLETA' in kinds(get(c,'versiones/1')['anomalias'])


def test_potential_duplicates_prefilter_size_hash_name_and_limits(analysis):
    c,db,user,_=analysis
    db.get(VersionDocumento,2).nombre_original='Factura Enero.pdf'
    db.get(VersionDocumento,3).nombre_original='factura-enero.PDF'
    db.get(VersionDocumento,3).sha256='a'*64
    db.commit()
    detail=get(c,'documentos/1')
    matches=[r for r in detail['comprobaciones_locales'] if r['tipo']=='POSIBLE_DUPLICADO']
    assert len(matches)==1 and matches[0]['similitud_nombre']==1
    assert matches[0]['relacionado']=={'pagina':'documento','id':2,'version_id':3}
    db.get(VersionDocumento,3).tamano_bytes=8;db.commit()
    assert not any(r['tipo']=='POSIBLE_DUPLICADO' for r in get(c,'documentos/1')['comprobaciones_locales'])
    user['id']=4
    assert not any(r['tipo']=='POSIBLE_DUPLICADO' for r in get(c,'documentos/1')['comprobaciones_locales'])


def test_candidate_and_version_limits_explicit_partial_results(analysis):
    c,db,user,storage=analysis
    db.get(VersionDocumento,2).nombre_original='Factura Enero.pdf'
    for i in range(70):
        db.add(Documento(id=100+i,codigo=f'CAND{i}',titulo='Candidate',tipo='TEST',estado='ACTIVE',
            area_id=1,responsable_id=7,created_by_id=1))
    db.flush()
    for i in range(70):
        db.add(VersionDocumento(id=100+i,documento_id=100+i,numero_version=1,
            nombre_original='Factura-Enero.pdf',storage_key=f'documents/candidate{i}',mime_type='application/pdf',
            tamano_bytes=7,sha256='a'*64,subido_por_id=1))
    for i in range(100):
        db.add(VersionDocumento(id=300+i,documento_id=1,numero_version=3+i,
            nombre_original='Factura Enero.pdf',storage_key=f'documents/version{i}',mime_type='application/pdf',
            tamano_bytes=7,sha256='b'*64,subido_por_id=1))
    db.commit()
    data=get(c,'documentos/1')
    assert data['candidatos_comparados']==64 and data['candidatos_truncados']
    assert data['versiones_comprobadas']==100 and not data['comprobacion_completa']
    user['id']=4
    data=get(c,'documentos/1')
    assert data['candidatos_comparados']==0 and not data['candidatos_truncados']


def test_storage_missing_and_malicious_routes_only_temporary(analysis):
    c,db,user,storage=analysis
    assert storage.base_path != service.storage_service.base_path or 'pytest' in str(storage.base_path).lower() or 'temp' in str(storage.base_path).lower()
    assert not get(c,'versiones/1')['comprobaciones_locales']
    db.get(VersionDocumento,1).storage_key='documents/nonexistent-file.txt';db.commit()
    assert 'ARCHIVO_NO_DISPONIBLE' in {r['tipo'] for r in get(c,'versiones/1')['comprobaciones_locales']}
    for key in ('../outside','..\\outside','/etc/passwd','C:/secret','\\\\host\\secret',
                'documents/%2e%2e/secret','documents/../../secret','documents/..\\secret'):
        assert rules.storage_status(storage,key)=='RUTA_NO_SEGURA'
    # No reads of file contents; existing temporary A/B/E identical and C/D distinct.
    a=storage.save_file(BytesIO(b'A'),'same.txt')
    b=storage.save_file(BytesIO(b'A'),'same.txt')
    other=storage.save_file(BytesIO(b'C'),'same.txt')
    e=storage.save_file(BytesIO(b'A'),'different.txt')
    assert a.sha256==b.sha256==e.sha256 and other.sha256!=a.sha256
    assert rules.storage_status(storage,a.storage_key) is None


def test_storage_symlink_rejected_without_target_access(tmp_path):
    from app.services.storage_service import StorageService
    root=tmp_path/'root';root.mkdir();(root/'documents').mkdir()
    target=tmp_path/'outside';target.write_bytes(b'not readable by analysis')
    link=root/'documents'/'link'
    try:link.symlink_to(target)
    except OSError:
        # Windows without symlink privilege: NTFS junction provides equivalent attack.
        import subprocess
        folder=tmp_path/'outside_dir';folder.mkdir()
        result=subprocess.run(['cmd','/c','mklink','/J',str(link),str(folder)],capture_output=True)
        assert result.returncode==0,'Neither symlink nor junction test supported'
    assert rules.storage_status(StorageService(root),'documents/link')=='RUTA_NO_SEGURA'


def test_analysis_never_writes_storage_or_opens_content(analysis,monkeypatch):
    c,db,user,storage=analysis
    import hashlib
    def fingerprint():
        return {p.relative_to(storage.base_path).as_posix():(p.stat().st_size,hashlib.sha256(p.read_bytes()).hexdigest())
                for p in storage.base_path.rglob('*') if p.is_file()}
    before=fingerprint()
    def forbidden(*args,**kwargs):raise AssertionError('Analysis attempted storage mutation/content verification')
    monkeypatch.setattr(storage,'save_file',forbidden)
    monkeypatch.setattr(storage,'delete_file',forbidden)
    monkeypatch.setattr(storage,'verify_file_integrity',forbidden)
    for endpoint in ENDPOINTS:get(c,endpoint)
    assert fingerprint()==before


def test_all_analysis_endpoints_require_authentication(analysis):
    from app.main import app
    from app.api.dependencies import current_user
    c,_,_,_=analysis
    override=app.dependency_overrides.pop(current_user)
    try:
        for endpoint in ENDPOINTS:
            assert c.get('/api/v1/analisis/'+endpoint).status_code==401
            assert c.get('/api/v1/analisis/'+endpoint,headers={'Authorization':'Bearer invalid'}).status_code==401
    finally:app.dependency_overrides[current_user]=override


def test_real_temporary_file_matrix_identical_different_name_and_different_content(analysis):
    c,db,user,storage=analysis
    specs=[('Factura Enero.txt',b'A'),('factura enero.TXT',b'A'),('Informe distinto.txt',b'C'),
           ('Factura Enero.txt',b'D'),('Otro titulo.txt',b'A')]
    for i,(name,content) in enumerate(specs,100):
        db.add(Documento(id=i,codigo=f'FILES{i}',titulo=name,tipo='TEST',estado='ACTIVE',
            area_id=1,responsable_id=4,created_by_id=1))
    db.flush()
    for i,(name,content) in enumerate(specs,100):
        info=storage.save_file(BytesIO(content),name)
        db.add(VersionDocumento(id=i,documento_id=i,numero_version=1,storage_key=info.storage_key,
            nombre_original=info.nombre_original,sha256=info.sha256,tamano_bytes=info.tamano_bytes,
            mime_type=info.mime_type,subido_por_id=1))
    db.commit()
    for vid in (100,101,104):
        data=get(c,f'versiones/{vid}')
        assert 'DUPLICATE_HASH' in kinds(data['anomalias'])
        assert not any(r['tipo']=='ARCHIVO_NO_DISPONIBLE' for r in data['comprobaciones_locales'])
    for vid in (102,103):assert 'DUPLICATE_HASH' not in kinds(get(c,f'versiones/{vid}')['anomalias'])
    same_name=get(c,'versiones/103')
    assert any(r['tipo']=='POSIBLE_DUPLICADO' and r['similitud_nombre']==1 for r in same_name['comprobaciones_locales'])


def test_audit_filter_exclusion_is_not_a_missing_current_reference(analysis):
    c,db,user,_=analysis
    db.get(Documento,1).version_vigente_id=3 # Cross-document but exists outside audit 1.
    db.commit()
    assert 'VERSION_VIGENTE_INCONGRUENTE' in kinds(get(c,documento_id=1))
    assert 'VERSION_VIGENTE_INCONGRUENTE' not in kinds(get(c,documento_id=1,auditoria_id=1))
