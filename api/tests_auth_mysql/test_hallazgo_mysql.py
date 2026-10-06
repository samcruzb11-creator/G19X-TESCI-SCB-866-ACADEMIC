"""7B shared adversarial contract plus InnoDB/FK/locking concurrency."""
from tests_unit.test_hallazgo_unit import *  # noqa: F403
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from sqlalchemy.exc import IntegrityError
from app.schemas.hallazgo import HallazgoCreate, HallazgoUpdate, HallazgoTransition, HallazgoLink
from app.schemas.auditoria import AuditoriaTransition
from app.services import auditoria_service

MYSQL_RBAC = True


@pytest.mark.parametrize('operation',['edit','state','link','create'])
def test_real_concurrent_mutations(findings,mysql_factory,operation):
    c,db,_,_=findings;stamp=detail(c)['updated_at'];db.rollback()
    barrier=Barrier(2)
    def mutate(index):
        with mysql_factory() as session:
            actor=session.get(Usuario,1)
            barrier.wait(timeout=10)
            try:
                if operation=='edit': result=service.edit(session,actor,1,HallazgoUpdate(titulo=f'Edit {index}',updated_at_esperado=stamp))
                elif operation=='state':result=service.transition(session,actor,1,HallazgoTransition(estado='IN_PROGRESS',estado_esperado='OPEN',updated_at_esperado=stamp))
                elif operation=='link':result=service.associate(session,actor,1,HallazgoLink(evidencia_id=1))
                else:result=service.create(session,actor,HallazgoCreate(**body(titulo=f'Created {index}')))
                return 200,result.numero
            except HTTPException as exc:return exc.status_code,None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(mutate,[1,2]))
    assert sorted(x[0] for x in results)==([200,200] if operation=='create' else [200,409])
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(EventoAuditoria))==(2 if operation=='create' else 1)
    if operation=='create':assert sorted(x[1] for x in results)==[2,3]
    if operation=='link':assert db.scalar(select(func.count()).select_from(HallazgoEvidencia))==1


@pytest.mark.parametrize('operation',['edit','state','link','create','logical','file'])
def test_close_wins_rejects_waiting_mutation_before_storage(findings,mysql_factory,monkeypatch,operation):
    c,fixture_db,_,storage=findings
    fixture_db.get(Auditoria,1).estado='IN_REVIEW';fixture_db.commit()
    finding_stamp=detail(c)['updated_at'];fixture_db.rollback()
    reached=Event()
    engine=mysql_factory.kw['bind']
    def record(conn,cursor,stmt,params,context,many):
        if 'FOR UPDATE' in stmt and 'FROM auditorias' in stmt and conn.info.get('waiting_7b'):
            reached.set()
    event.listen(engine,'before_cursor_execute',record)
    def forbidden(*a,**kw):pytest.fail('Closed audit must reject before storage')
    monkeypatch.setattr(storage,'save_file',forbidden)
    def mutate():
        with mysql_factory() as db:
            db.connection().info['waiting_7b']=True
            actor=db.get(Usuario,1)
            try:
                if operation=='edit':service.edit(db,actor,1,HallazgoUpdate(titulo='Race',updated_at_esperado=finding_stamp))
                elif operation=='state':service.transition(db,actor,1,HallazgoTransition(estado='IN_PROGRESS',estado_esperado='OPEN',updated_at_esperado=finding_stamp))
                elif operation=='link':service.associate(db,actor,1,HallazgoLink(evidencia_id=1))
                elif operation=='create':service.create(db,actor,HallazgoCreate(**body()))
                elif operation=='logical':evidencia_service.registrar_evidencia_logica(db,EvidenciaCreate(auditoria_id=1,titulo='Proof',tipo='NOTE',hallazgo_id=1),1)
                else:evidencia_service.registrar_evidencia_archivo(db,1,'Proof',1,io.BytesIO(b'proof'),'proof.txt',hallazgo_id=1)
            except HTTPException as exc:return exc.status_code
            finally:db.connection().info.pop('waiting_7b',None)
            return 200
    try:
        with mysql_factory() as closer, ThreadPoolExecutor(max_workers=1) as pool:
            actor=closer.get(Usuario,1)
            audit=auditoria_service.resource(closer,actor,1,action='auditoria.transition',locking=True)
            close_stamp=audit.updated_at
            pending=pool.submit(mutate)
            assert reached.wait(10),'Mutation did not reach the shared audit lock'
            assert not pending.done(),'Mutation crossed a held audit lock'
            auditoria_service.transition(closer,actor,1,AuditoriaTransition(estado='COMPLETED',estado_esperado='IN_REVIEW',updated_at_esperado=close_stamp))
            assert pending.result(timeout=10)==409
    finally:event.remove(engine,'before_cursor_execute',record)
    fixture_db.expire_all()
    assert fixture_db.get(Auditoria,1).estado=='COMPLETED'
    assert fixture_db.get(Hallazgo,1).titulo=='Finding 1'
    assert fixture_db.scalar(select(func.count()).select_from(EventoAuditoria))==1
    assert fixture_db.scalar(select(func.count()).select_from(HallazgoEvidencia))==0
    assert fixture_db.scalar(select(func.count()).select_from(Evidencia))==4


def test_upload_wins_close_waits_until_file_link_and_events_committed(findings,mysql_factory,monkeypatch):
    c,fixture_db,_,storage=findings
    fixture_db.get(Auditoria,1).estado='IN_REVIEW';fixture_db.commit()
    audit_stamp=fixture_db.get(Auditoria,1).updated_at;fixture_db.rollback()
    uploading=Event();release=Event();closing=Event();save=storage.save_file
    def paused_save(*args,**kwargs):
        uploading.set();assert release.wait(10)
        return save(*args,**kwargs)
    monkeypatch.setattr(storage,'save_file',paused_save)
    def upload():
        with mysql_factory() as db:
            result=evidencia_service.registrar_evidencia_archivo(db,1,'Racing upload',1,io.BytesIO(b'proof'),'proof.txt',hallazgo_id=1)
            return result.id,result.storage_key
    def close():
        with mysql_factory() as db:
            actor=db.get(Usuario,1);closing.set()
            return auditoria_service.transition(db,actor,1,AuditoriaTransition(estado='COMPLETED',estado_esperado='IN_REVIEW',updated_at_esperado=audit_stamp)).estado
    with ThreadPoolExecutor(max_workers=2) as pool:
        up=pool.submit(upload);assert uploading.wait(10)
        end=pool.submit(close);assert closing.wait(10);assert not end.done()
        release.set();evidence_id,key=up.result(timeout=10);assert end.result(timeout=10)=='COMPLETED'
    fixture_db.expire_all()
    assert fixture_db.get(HallazgoEvidencia,(1,evidence_id)) is not None
    assert storage.get_absolute_path(key).read_bytes()==b'proof'
    assert fixture_db.scalar(select(func.count()).select_from(EventoAuditoria))==3


@pytest.mark.parametrize('ids',[(999,1),(1,999),(999,999)])
def test_real_link_fk_constraints(findings,ids):
    _,db,_,_=findings
    db.add(HallazgoEvidencia(hallazgo_id=ids[0],evidencia_id=ids[1],vinculada_por_id=1))
    with pytest.raises(IntegrityError):db.commit()
    db.rollback()
    assert db.scalar(select(func.count()).select_from(HallazgoEvidencia))==0


def test_real_composite_primary_key_prevents_duplicates(findings):
    _,db,_,_=findings
    db.add(HallazgoEvidencia(hallazgo_id=1,evidencia_id=1,vinculada_por_id=1));db.commit()
    db.add(HallazgoEvidencia(hallazgo_id=1,evidencia_id=1,vinculada_por_id=1))
    with pytest.raises(IntegrityError):db.commit()
    db.rollback()
    assert db.scalar(select(func.count()).select_from(HallazgoEvidencia))==1


def test_number_after_old_repeatable_read_snapshot(findings,mysql_factory):
    _,fixture_db,_,_=findings;fixture_db.rollback()
    with mysql_factory() as older:
        actor=older.get(Usuario,1)
        assert older.scalar(select(func.max(Hallazgo.numero)).where(Hallazgo.auditoria_id==1))==1
        with mysql_factory() as newer:
            assert service.create(newer,newer.get(Usuario,1),HallazgoCreate(**body())).numero==2
        assert service.create(older,actor,HallazgoCreate(**body())).numero==3
