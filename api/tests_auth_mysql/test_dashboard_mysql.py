"""Run every 7D contract on MySQL 8/InnoDB through guarded temporary schemas."""
from tests_unit.test_dashboard_unit import *  # noqa: F403
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
from sqlalchemy import insert
from app.models.entities import Evidencia
from app.schemas.hallazgo import HallazgoTransition
from app.schemas.aprobacion import DecisionCommand
from app.schemas.auditoria import AuditoriaTransition, AuditoriaUpdate
from app.services import hallazgo_service, aprobacion_service, auditoria_service, dashboard_queries

MYSQL_RBAC = True


@pytest.mark.parametrize('mutation',['finding_close','final_approval','audit_close','new_version','reassign'])
def test_repeatable_read_snapshot_under_real_concurrent_mutations(dashboard,mysql_factory,mutation):
    c,fixture,actor,storage=dashboard
    if mutation=='final_approval':fixture.get(RondaAprobacion,1).estado='IN_REVIEW'
    if mutation=='reassign':fixture.get(Auditoria,1).estado='IN_PROGRESS'
    fixture.commit();fixture.rollback()
    reader_id=2 if mutation=='reassign' else 1
    actor['id']=reader_id
    baseline=get(c);baseline.pop('generado_en');fixture.rollback()
    reached=Event();release=Event();engine=mysql_factory.kw['bind']
    def pause(conn,cursor,stmt,*args):
        if conn.info.get('dashboard_reader') and 'FROM auditorias' in stmt and 'GROUP BY' in stmt:
            reached.set();assert release.wait(15)
    event.listen(engine,'after_cursor_execute',pause)
    def read():
        with mysql_factory() as db:
            assert db.connection().get_isolation_level()=='REPEATABLE READ'
            db.connection().info['dashboard_reader']=True
            try:return service.summary(db,db.get(Usuario,reader_id),DashboardPage()).model_dump(mode='json')
            finally:db.connection().info.pop('dashboard_reader',None)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            result=pool.submit(read);assert reached.wait(10)
            with mysql_factory() as writer:
                admin=writer.get(Usuario,1)
                if mutation=='finding_close':
                    row=writer.scalar(select(Hallazgo).where(Hallazgo.auditoria_id==1,Hallazgo.numero==3))
                    hallazgo_service.transition(writer,admin,row.id,HallazgoTransition(estado='CLOSED',
                        estado_esperado='PENDING_VERIFICATION',updated_at_esperado=row.updated_at,resolucion='Verified'))
                elif mutation=='final_approval':
                    row=writer.get(DecisionAprobacion,1)
                    aprobacion_service.decide(writer,writer.get(Usuario,5),1,DecisionCommand(
                        estado='APPROVED',updated_at_esperado=row.updated_at))
                elif mutation=='audit_close':
                    row=writer.get(Auditoria,1)
                    auditoria_service.transition(writer,admin,1,AuditoriaTransition(estado='COMPLETED',
                        estado_esperado='IN_REVIEW',updated_at_esperado=row.updated_at))
                elif mutation=='new_version':
                    from io import BytesIO
                    from starlette.datastructures import UploadFile
                    from app.services.documento_service import documento_service
                    documento_service.crear_version_desde_upload(writer,5,
                        UploadFile(BytesIO(b'new version'),filename='snapshot.txt'),1)
                else:
                    row=writer.get(Auditoria,1)
                    auditoria_service.edit(writer,admin,1,AuditoriaUpdate(
                        responsable_id=6,updated_at_esperado=row.updated_at))
            release.set();old=result.result(timeout=15);old.pop('generado_en')
            assert old==baseline  # Entire response is one snapshot, not mixed counts/alerts.
    finally:
        release.set();event.remove(engine,'after_cursor_execute',pause)
    fixture.expire_all();fixture.rollback()
    new=get(c);new.pop('generado_en');assert new!=baseline
    if mutation=='reassign':assert new['indicadores']['auditorias']['total']==1


def test_bigint_max_context_and_strict_legacy_event_matching(dashboard):
    c,_,user,_=dashboard;user['id']=2
    assert c.get('/api/v1/dashboard/resumen',params={'auditoria_id':str(2**64-1)}).status_code==404


def test_volume_query_budget_scopes_explain_and_elapsed(dashboard,mysql_factory,tmp_path):
    c,db,actor,_=dashboard
    # Data exists only inside the random schema owned by mysql_factory.
    assert db.get_bind().url.database.startswith('sistema_trazabilidad_test_auth_')
    db.execute(insert(Usuario),[dict(id=1000+i,nombre=f'Synthetic {i}',correo=f'volume{i}@example.invalid',
        correo_normalizado=f'volume{i}@example.invalid',password_hash='unused',rol='APROBADOR',activo=True) for i in range(800)])
    db.execute(insert(Auditoria),[dict(id=1000+i,codigo=f'VOLA{i}',nombre=f'Volume audit {i}',alcance='TEST',
        estado='IN_PROGRESS',responsable_id=2 if i%2==0 else 6,created_by_id=1) for i in range(200)])
    db.execute(insert(Documento),[dict(id=1000+i,codigo=f'VOLD{i}',titulo=f'Volume doc {i}',tipo='TEST',
        estado='ACTIVE',area_id=1,responsable_id=4 if i%2==0 else 7,created_by_id=1) for i in range(2000)])
    db.execute(insert(VersionDocumento),[dict(id=1000+i,documento_id=1000+i//2,numero_version=1+i%2,
        storage_key=f'synthetic/volume/{i}',nombre_original='synthetic.txt',mime_type='text/plain',
        tamano_bytes=0,sha256='0'*64,subido_por_id=1) for i in range(3600)])
    db.execute(insert(DocumentoAuditoria),[dict(auditoria_id=1000+i%200,documento_id=1000+i,
        version_documento_id=1000+i*2,proposito='TEST',asociado_por_id=1) for i in range(1800)])
    db.execute(insert(Hallazgo),[dict(id=1000+i,auditoria_id=1000+i%200,numero=1+i//200,
        titulo=f'Volume finding {i}',descripcion='TEST',categoria='TEST',severidad='MEDIUM',
        estado='OPEN',created_by_id=1) for i in range(2000)])
    db.execute(insert(Evidencia),[dict(auditoria_id=1000+i%200,tipo='NOTE',titulo=f'Volume evidence {i}',
        registrada_por_id=1) for i in range(2000)])
    db.execute(insert(RondaAprobacion),[dict(id=1000+i,version_documento_id=1000+i*2,
        numero_ronda=1,estado='IN_REVIEW',solicitada_por_id=1) for i in range(1800)])
    db.execute(insert(DecisionAprobacion),[dict(ronda_aprobacion_id=1000+i,aprobador_id=5,
        estado='PENDING') for i in range(1800)])
    db.execute(insert(DecisionAprobacion),[dict(ronda_aprobacion_id=1000+i,aprobador_id=1000+i%800,
        estado='PENDING') for i in range(1800)])
    db.execute(insert(EventoAuditoria),[dict(accion='CREACION_RONDA_APROBACION',entidad_tipo='RONDA_APROBACION',
        entidad_id=str(1000+i),actor_id=1) for i in range(1800)])
    db.execute(insert(EventoAuditoria),[dict(accion='CREACION_AUDITORIA',entidad_tipo='AUDITORIA',
        entidad_id=str(1000+i%200),actor_id=1) for i in range(2200)])
    db.commit();db.rollback()
    report={'counts':{},'roles':{}}
    for model in (Usuario,Auditoria,Documento,VersionDocumento,Hallazgo,Evidencia,RondaAprobacion,DecisionAprobacion,EventoAuditoria):
        report['counts'][model.__tablename__]=db.scalar(select(func.count()).select_from(model))
    for id,role in [(1,'ADMIN'),(2,'AUDITOR_INTERNO'),(3,'AUDITOR_EXTERNO'),(4,'RESPONSABLE_AREA'),(5,'APROBADOR')]:
        actor['id']=id;get(c)
        statements=[]
        def capture(conn,cursor,stmt,params,*args):
            if stmt.lstrip().upper().startswith('SELECT'):statements.append((stmt,params))
        event.listen(db.get_bind(),'before_cursor_execute',capture)
        samples=[]
        try:
            for _ in range(3):
                statements.clear();start=time.perf_counter();data=get(c,limit=5)
                samples.append(time.perf_counter()-start)
                assert len(statements)<=12
        finally:event.remove(db.get_bind(),'before_cursor_execute',capture)
        assert max(samples)<5, (role,samples)
        if id==2:
            assert data['indicadores']['auditorias']['total']==102
            assert data['indicadores']['hallazgos']['total']==1010
            assert data['indicadores']['aprobaciones']['total']==902
        plans=[]
        for sql,params in statements:
            assert sql.lstrip().upper().startswith('SELECT')
            rows=db.connection().exec_driver_sql('EXPLAIN '+sql,params).mappings().all()
            plans.append({'sql':sql,'plan':[dict(r) for r in rows]})
        report['roles'][role]={'seconds':samples,'selects':len(statements),'explain':plans}
    artifact=tmp_path/'dashboard-volume-explain.json'
    artifact.write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
