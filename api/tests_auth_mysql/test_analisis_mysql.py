"""7E contracts on real MySQL 8 using guarded ephemeral schemas only."""
from tests_unit.test_analisis_unit import *  # noqa: F403

MYSQL_RBAC = True

from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
from sqlalchemy import insert, text, func
from fastapi import Response, HTTPException
from app.routers.analisis import evaluate
from app.models.entities import RondaAprobacion, DecisionAprobacion, EventoAuditoria


def test_unsigned_bigint_boundary_on_real_mysql(analysis):
    c,db,user,_=analysis
    for resource in ('documentos','versiones'):
        assert c.get('/api/v1/analisis/'+resource+'/'+str(2**64-1)).status_code==404
    assert c.get('/api/v1/analisis/resumen',params={'documento_id':str(2**64-1)}).status_code==404


@pytest.mark.parametrize('mutation',['new_version','upload','legacy_metadata_change','audit_close','approval','scope_revoke','role_revoke','assignment_revoke'])
def test_concurrency_snapshot_and_fresh_scope_barrier(analysis,mysql_factory,mutation):
    c,fixture,actor,storage=analysis
    uid=5 if mutation=='assignment_revoke' else 2 if mutation=='scope_revoke' else 1
    actor['id']=uid;baseline=stable(get(c,'resumen'));fixture.rollback()
    reached=Event();release=Event();engine=mysql_factory.kw['bind']
    def pause(conn,cursor,sql,*args):
        if conn.info.get('analysis_reader') and 'derived_analysis' in sql and 'GROUP BY' in sql:
            reached.set();assert release.wait(15)
    event.listen(engine,'after_cursor_execute',pause)
    def reader():
        with mysql_factory() as db:
            assert db.connection().get_isolation_level()=='REPEATABLE READ'
            db.connection().info['analysis_reader']=True
            try:
                user=db.get(Usuario,uid);filters=AnalysisContext()
                return evaluate(db,user,filters,Response(),lambda stamp:service.summary(db,user,filters,stamp))
            except HTTPException as exc:return exc.status_code
            finally:db.connection().info.pop('analysis_reader',None)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(reader);assert reached.wait(10)
            with mysql_factory() as writer:
                if mutation == 'new_version':
                    from app.services.documento_service import documento_service
                    from starlette.datastructures import UploadFile
                    documento_service.crear_version_desde_upload(writer,1,
                        UploadFile(BytesIO(b'fixture'),filename='concurrent.txt'),1)
                elif mutation=='upload':
                    info=storage.save_file(BytesIO(b'new temporary evidence'),'concurrent.txt',category='evidence')
                    writer.add(Evidencia(auditoria_id=1,tipo='FILE',titulo='Concurrent file',storage_key=info.storage_key,
                        sha256=info.sha256,tamano_bytes=info.tamano_bytes,nombre_original=info.nombre_original,
                        mime_type=info.mime_type,registrada_por_id=1));writer.commit()
                elif mutation=='legacy_metadata_change':
                    writer.get(VersionDocumento,1).sha256='e'*64;writer.commit()
                elif mutation=='audit_close':
                    row=writer.get(Auditoria,1);row.estado='COMPLETED';row.completada_en=datetime.now();writer.commit()
                elif mutation=='approval':
                    row=writer.get(DecisionAprobacion,1);row.estado='APPROVED';row.decidida_en=datetime.now();writer.commit()
                elif mutation=='scope_revoke':
                    writer.get(Auditoria,1).responsable_id=6;writer.commit()
                elif mutation=='role_revoke':
                    writer.get(Usuario,1).activo=False;writer.commit()
                else:
                    writer.get(DecisionAprobacion,1).aprobador_id=8;writer.commit()
            release.set();result=future.result(timeout=15)
            if mutation in ('new_version','upload','scope_revoke','assignment_revoke'):assert result==409
            elif mutation=='role_revoke':assert result==403
            else:assert stable(result.model_dump(mode='json'))==baseline
    finally:
        release.set();event.remove(engine,'after_cursor_execute',pause)
    fixture.rollback();fixture.expire_all()
    if mutation=='scope_revoke':
        assert c.get('/api/v1/analisis/documentos/1').status_code==404
    elif mutation=='legacy_metadata_change':assert stable(get(c,'resumen'))!=baseline


def test_legacy_corruption_unknown_collation_duplicate_numbers_and_file_metadata(analysis):
    c,db,user,_=analysis
    name=db.get_bind().url.database
    assert name.startswith('sistema_trazabilidad_test_auth_') and name!='sistema_trazabilidad'
    connection=db.connection()
    # Only guarded ephemeral schema, restore the real constraints in finally.
    connection.exec_driver_sql('CREATE INDEX analysis_test_document ON versiones_documento(documento_id)')
    connection.exec_driver_sql('ALTER TABLE versiones_documento DROP INDEX uq_versiones_documento_numero')
    try:
        db.get(VersionDocumento,2).numero_version=1
        db.get(Documento,1).estado='active' # CHECK collation permits; exact rule does not
        db.add(Evidencia(id=9,auditoria_id=1,tipo='FILE',titulo='Incomplete FILE',storage_key='',
            sha256='Z'*64,tamano_bytes=0,nombre_original='',mime_type='',registrada_por_id=1))
        db.commit()
        data=get(c,limit=100)
        assert {'NUMERO_VERSION_DUPLICADO','ESTADO_DESCONOCIDO','METADATA_INCOMPLETA'}<=kinds(data)
        item=next(r for r in data['items'] if r['recurso']=='evidencia' and r['recurso_id']==9)
        assert 'SHA-256 ausente o inválido' in item['evidencia_tecnica']
        assert 'Tamaño ausente o negativo' not in item['evidencia_tecnica']
    finally:
        db.rollback();db.get(VersionDocumento,2).numero_version=2;db.commit()
        db.connection().exec_driver_sql('ALTER TABLE versiones_documento ADD CONSTRAINT uq_versiones_documento_numero UNIQUE(documento_id,numero_version)')
        db.connection().exec_driver_sql('DROP INDEX analysis_test_document ON versiones_documento');db.commit()


def test_legacy_missing_reference_admin_only(analysis):
    c,db,user,_=analysis
    assert db.get_bind().url.database.startswith('sistema_trazabilidad_test_auth_')
    conn=db.connection()
    try:
        conn.exec_driver_sql('SET FOREIGN_KEY_CHECKS=0')
        conn.exec_driver_sql('UPDATE documentos SET version_vigente_id=999999 WHERE id=1')
        conn.exec_driver_sql('SET FOREIGN_KEY_CHECKS=1');db.commit()
        assert 'VERSION_VIGENTE_INCONGRUENTE' in kinds(get(c,documento_id=1))
        user['id']=4
        assert 'VERSION_VIGENTE_INCONGRUENTE' not in kinds(get(c,documento_id=1))
    finally:
        db.rollback();db.connection().exec_driver_sql('SET FOREIGN_KEY_CHECKS=1')
        db.connection().exec_driver_sql('UPDATE documentos SET version_vigente_id=2 WHERE id=1');db.commit()


def test_revoked_session_during_snapshot_discarded_at_fresh_barrier(analysis,mysql_factory):
    from app.models.auth import AuthSession
    from datetime import timezone
    c,db,user,_=analysis
    sid='7'*64
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(AuthSession(sid=sid,usuario_id=1,created_at=now,expires_at=now+timedelta(minutes=5)))
    db.commit();db.rollback()
    with mysql_factory() as reader:
        actor=reader.get(Usuario,1)
        retained=reader.get(AuthSession,sid)
        signature=service.visibility_digest(reader,actor)
        with mysql_factory() as writer:
            writer.get(AuthSession,sid).revoked_at=now;writer.commit()
        assert retained.revoked_at is None # Old snapshot remains coherent.
        with pytest.raises(HTTPException) as exc:service.fresh_authorization(reader,actor,signature)
        assert exc.value.status_code==401


def test_volume_explain_budget_bounded_matching_no_quadratic_pairs(analysis,mysql_factory,tmp_path):
    c,db,actor,_=analysis
    assert db.get_bind().url.database.startswith('sistema_trazabilidad_test_auth_')
    db.execute(insert(Usuario),[dict(id=1000+i,nombre=f'Synthetic {i}',correo=f'v{i}@example.invalid',
        correo_normalizado=f'v{i}@example.invalid',password_hash='unused',rol='APROBADOR',activo=True) for i in range(1000)])
    db.execute(insert(Auditoria),[dict(id=1000+i,codigo=f'VOLA{i}',nombre=f'Volume audit {i}',alcance='TEST',
        estado='IN_PROGRESS',responsable_id=2 if i%2==0 else 6,created_by_id=1) for i in range(200)])
    db.execute(insert(Documento),[dict(id=1000+i,codigo=f'VOLD{i}',titulo=f'Volume doc {i}',tipo='TEST',
        estado='ACTIVE',area_id=1,responsable_id=4 if i%2==0 else 7,created_by_id=1) for i in range(2000)])
    db.execute(insert(VersionDocumento),[dict(id=1000+i,documento_id=1000+i//2,numero_version=1+i%2,
        storage_key=f'documents/synthetic/{i}',nombre_original=f'Factura Enero {i%10:02}.pdf',mime_type='application/pdf',
        tamano_bytes=7,sha256=f'{i//2%3:064x}',subido_por_id=1) for i in range(3600)])
    # A pathological group with thousands of identical hashes must remain linear in output size.
    db.execute(insert(DocumentoAuditoria),[dict(auditoria_id=1000+i%200,documento_id=1000+i,
        version_documento_id=1000+i*2,proposito='TEST',asociado_por_id=1) for i in range(1800)])
    db.execute(insert(Evidencia),[dict(auditoria_id=1000+i%200,tipo='NOTE',titulo=f'Volume evidence {i}',
        registrada_por_id=1) for i in range(2000)])
    db.execute(insert(Hallazgo),[dict(id=1000+i,auditoria_id=1000+i%200,numero=1+i//200,
        titulo=f'Volume finding {i}',descripcion='TEST',categoria='TEST',severidad='MEDIUM',estado='OPEN',
        created_by_id=1) for i in range(2000)])
    db.execute(insert(RondaAprobacion),[dict(id=1000+i,version_documento_id=1000+i*2,
        numero_ronda=1,estado='IN_REVIEW',solicitada_por_id=1) for i in range(1800)])
    db.execute(insert(DecisionAprobacion),[dict(ronda_aprobacion_id=1000+i,aprobador_id=5,estado='PENDING') for i in range(1800)])
    db.execute(insert(DecisionAprobacion),[dict(ronda_aprobacion_id=1000+i,aprobador_id=1000+i%1000,estado='PENDING') for i in range(1800)])
    db.execute(insert(EventoAuditoria),[dict(accion='CREACION_RONDA_APROBACION',entidad_tipo='RONDA_APROBACION',
        entidad_id=str(1000+i%1800),actor_id=1) for i in range(4000)])
    db.commit();db.rollback()
    # Bulk-loaded ephemeral tables need representative optimizer statistics.
    # This touches only the guarded test schema, never the real database.
    for model in (Usuario,Auditoria,Documento,VersionDocumento,DocumentoAuditoria,Evidencia,
                  Hallazgo,RondaAprobacion,DecisionAprobacion,EventoAuditoria,HallazgoEvidencia):
        db.connection().exec_driver_sql('ANALYZE TABLE `'+model.__tablename__+'`').all()
    db.commit()
    report={'counts':{},'roles':{}}
    for model in (Usuario,Auditoria,Documento,VersionDocumento,Evidencia,Hallazgo,RondaAprobacion,DecisionAprobacion,EventoAuditoria):
        report['counts'][model.__tablename__]=db.scalar(select(func.count()).select_from(model))
    for uid,doc,version in [(1,1000,1000),(2,1000,1000),(3,3,4),(4,1000,1000),(5,1000,1000)]:
        actor['id']=uid;role=db.get(Usuario,uid).rol;report['roles'][role]={}
        for endpoint in ('resumen','anomalias',f'documentos/{doc}',f'versiones/{version}'):
            statements=[]
            def capture(conn,cursor,sql,params,*args):
                if sql.lstrip().upper().startswith(('SELECT','WITH')):statements.append((sql,params))
            event.listen(db.get_bind(),'before_cursor_execute',capture)
            try:
                start=time.perf_counter();data=get(c,endpoint);elapsed=time.perf_counter()-start
            finally:event.remove(db.get_bind(),'before_cursor_execute',capture)
            # The fixture's checkout guard SELECT DATABASE() is not an application query.
            relevant=[(s,p) for s,p in statements if s.strip().upper()!='SELECT DATABASE()']
            assert len(relevant)<=10,(role,endpoint,len(relevant))
            plans=[]
            for sql,params in relevant:
                plan=db.connection().exec_driver_sql('EXPLAIN '+sql,params).mappings().all()
                plans.append({'sql':sql,'plan':[dict(r) for r in plan]})
            report['roles'][role][endpoint]={'seconds':elapsed,'selects':len(relevant),'explain':plans}
            (tmp_path/'analysis-volume-explain.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
            assert elapsed<5,(role,endpoint,elapsed)
            if endpoint.startswith(('documentos','versiones')):
                assert data['candidatos_comparados']<=64 and data['versiones_comprobadas']<=100
            if endpoint=='resumen' and uid==1:
                assert data['por_tipo']['DUPLICATE_HASH']==3605
                assert data['total']<3605*8+2004
    (tmp_path/'analysis-volume-explain.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
