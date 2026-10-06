"""Schema-005 InnoDB contracts and actual races on a random guarded schema."""
from tests_unit.test_aprobacion_unit import *  # noqa: F403
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from sqlalchemy.exc import IntegrityError, OperationalError
from app.schemas.aprobacion import RondaCreate, RondaCommand, DecisionCommand
from app.schemas.auditoria import AuditoriaTransition
from app.services import auditoria_service

MYSQL_RBAC = True


@pytest.mark.parametrize('op',['duplicate','opposite','two','create','finalize','start'])
def test_concurrent_mutations_consistent_no_ghost_events(approvals,mysql_factory,op):
    c,fixture,actor,_=approvals
    if op in {'duplicate','opposite','two'}:
        if op=='two':
            fixture.add(Decision(ronda_aprobacion_id=1,aprobador_id=8,estado='PENDING'));fixture.commit()
        command(c,'iniciar')
    if op=='finalize':
        command(c,'iniciar')
        d=fixture.get(Decision,1);d.estado='APPROVED';d.decidida_en=service.now();fixture.commit()
    stamp=fixture.get(Ronda,1).updated_at
    vote_stamps={d.aprobador_id:d.updated_at for d in fixture.scalars(select(Decision).where(Decision.ronda_aprobacion_id==1))}
    fixture.rollback(); barrier=Barrier(2)
    def mutate(index):
        with mysql_factory() as db:
            user=db.get(Usuario,8 if op=='two' and index==2 else 5 if op in {'duplicate','opposite','two'} else 1)
            barrier.wait(timeout=10)
            try:
                if op in {'duplicate','opposite','two'}:
                    service.decide(db,user,1,DecisionCommand(estado='REJECTED' if op=='opposite' and index==2 else 'APPROVED',updated_at_esperado=vote_stamps[user.id]))
                elif op=='create':service.create(db,user,RondaCreate(**body()))
                else:service.command(db,user,1,RondaCommand(estado_esperado='IN_REVIEW' if op=='finalize' else 'PENDING',updated_at_esperado=stamp),'finalizar' if op=='finalize' else 'iniciar')
                return 200
            except HTTPException as exc:return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(mutate,[1,2]))
    assert sorted(results)==([200,200] if op=='two' else [200,409]),results
    fixture.expire_all()
    if op in {'duplicate','opposite','two'}:
        row=fixture.get(Ronda,1)
        states=list(fixture.scalars(select(Decision.estado).where(Decision.ronda_aprobacion_id==1)))
        assert row.estado==('REJECTED' if 'REJECTED' in states else 'APPROVED')
        assert fixture.scalar(select(func.count()).select_from(EventoAuditoria))==(4 if op=='two' else 3)
    elif op=='create':
        assert fixture.scalar(select(func.count()).select_from(Ronda))==5
        assert fixture.scalar(select(func.count()).select_from(EventoAuditoria))==1
    elif op=='finalize':assert fixture.scalar(select(func.count()).select_from(EventoAuditoria))==2
    else:assert fixture.scalar(select(func.count()).select_from(EventoAuditoria))==1


@pytest.mark.parametrize('op',['create','decision','iniciar','cancelar','finalizar'])
@pytest.mark.parametrize('target',['COMPLETED','CANCELLED'])
def test_audit_close_wins_all_waiting_approval_writes(approvals,mysql_factory,op,target):
    c,fixture,actor,_=approvals
    if op in {'decision','finalizar'}:command(c,'iniciar')
    round_stamp=fixture.get(Ronda,1).updated_at;state=fixture.get(Ronda,1).estado
    decision_stamp=fixture.get(Decision,1).updated_at
    before=fixture.scalar(select(func.count()).select_from(EventoAuditoria));fixture.rollback()
    reached=Event();engine=mysql_factory.kw['bind']
    def observe(conn,cursor,stmt,*args):
        if 'FOR UPDATE' in stmt and 'FROM auditorias' in stmt and conn.info.get('approval_wait'):
            reached.set()
    event.listen(engine,'before_cursor_execute',observe)
    def mutate():
        with mysql_factory() as db:
            db.connection().info['approval_wait']=True
            user=db.get(Usuario,5 if op=='decision' else 1)
            try:
                if op=='decision':service.decide(db,user,1,DecisionCommand(estado='APPROVED',updated_at_esperado=decision_stamp))
                elif op=='create':service.create(db,user,RondaCreate(**body(version_documento_id=1)))
                else:service.command(db,user,1,RondaCommand(estado_esperado=state,updated_at_esperado=round_stamp),op)
                return 200
            except HTTPException as exc:return exc.status_code
            finally:db.connection().info.pop('approval_wait',None)
    try:
        with mysql_factory() as closer,ThreadPoolExecutor(max_workers=1) as pool:
            audit=closer.scalar(select(Auditoria).where(Auditoria.id==1).with_for_update())
            pending=pool.submit(mutate);assert reached.wait(10);assert not pending.done()
            if target=='COMPLETED':auditoria_service.transition(closer,closer.get(Usuario,1),1,
                AuditoriaTransition(estado='COMPLETED',estado_esperado='IN_REVIEW',updated_at_esperado=audit.updated_at))
            else:audit.estado='CANCELLED';closer.commit()
            assert pending.result(timeout=10)==409
    finally:event.remove(engine,'before_cursor_execute',observe)
    fixture.expire_all()
    assert fixture.get(Ronda,1).estado==state and fixture.get(Decision,1).estado=='PENDING'
    assert fixture.scalar(select(func.count()).select_from(EventoAuditoria))==before+(target=='COMPLETED')


def test_decision_wins_audit_close_waits_transaction(approvals,mysql_factory,monkeypatch):
    c,fixture,_,_=approvals;command(c,'iniciar')
    stamp=fixture.get(Decision,1).updated_at;end_stamp=fixture.get(Auditoria,1).updated_at;fixture.rollback()
    reached=Event();release=Event();closing=Event();original=service._log_evento
    def paused(db,**kw):
        if kw['accion']=='DECISION_APROBACION':reached.set();assert release.wait(10)
        return original(db,**kw)
    monkeypatch.setattr(service,'_log_evento',paused)
    def vote_thread():
        with mysql_factory() as db:return service.decide(db,db.get(Usuario,5),1,DecisionCommand(estado='APPROVED',updated_at_esperado=stamp)).estado
    def close_thread():
        with mysql_factory() as db:
            closing.set()
            return auditoria_service.transition(db,db.get(Usuario,1),1,AuditoriaTransition(estado='COMPLETED',estado_esperado='IN_REVIEW',updated_at_esperado=end_stamp)).estado
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(vote_thread);assert reached.wait(10)
        second=pool.submit(close_thread);assert closing.wait(10);assert not second.done()
        release.set();assert first.result(timeout=10)=='APPROVED';assert second.result(timeout=10)=='COMPLETED'
    fixture.expire_all();assert fixture.scalar(select(func.count()).select_from(EventoAuditoria))==4


@pytest.mark.parametrize('winner',['cancelar','finalizar'])
def test_last_vote_vs_round_close(approvals,mysql_factory,winner):
    c,fixture,_,_=approvals;command(c,'iniciar')
    round_stamp=fixture.get(Ronda,1).updated_at;decision_stamp=fixture.get(Decision,1).updated_at
    fixture.rollback();barrier=Barrier(2)
    def mutate(voting):
        with mysql_factory() as db:
            user=db.get(Usuario,5 if voting else 1);barrier.wait(timeout=10)
            try:
                if voting:service.decide(db,user,1,DecisionCommand(estado='APPROVED',updated_at_esperado=decision_stamp))
                else:service.command(db,user,1,RondaCommand(estado_esperado='IN_REVIEW',updated_at_esperado=round_stamp),winner)
                return 200
            except HTTPException as exc:return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(mutate,[True,False]))
    assert sorted(outcomes)==[200,409]
    fixture.expire_all();row=fixture.get(Ronda,1);decision=fixture.get(Decision,1)
    assert (row.estado,decision.estado) in [('APPROVED','APPROVED'),('CANCELLED','PENDING')]
    count=fixture.scalar(select(func.count()).select_from(EventoAuditoria))
    assert count==(3 if row.estado=='APPROVED' else 2)


def test_approver_deactivated_while_waiting_no_confirmation(approvals,mysql_factory):
    c,fixture,_,_=approvals;command(c,'iniciar')
    stamp=fixture.get(Decision,1).updated_at;fixture.rollback()
    reached=Event();engine=mysql_factory.kw['bind']
    def observe(conn,cursor,stmt,*args):
        if 'FOR UPDATE' in stmt and 'FROM usuarios' in stmt and conn.info.get('deactivate_wait'):reached.set()
    event.listen(engine,'before_cursor_execute',observe)
    def mutate():
        with mysql_factory() as db:
            db.connection().info['deactivate_wait']=True
            actor=db.get(Usuario,5)
            try:service.decide(db,actor,1,DecisionCommand(estado='APPROVED',updated_at_esperado=stamp));return 200
            except HTTPException as exc:return exc.status_code
            finally:db.connection().info.pop('deactivate_wait',None)
    try:
        with mysql_factory() as disabling,ThreadPoolExecutor(max_workers=1) as pool:
            user=disabling.scalar(select(Usuario).where(Usuario.id==5).with_for_update())
            pending=pool.submit(mutate);assert reached.wait(10);assert not pending.done()
            user.activo=False;disabling.commit();assert pending.result(timeout=10)==403
    finally:event.remove(engine,'before_cursor_execute',observe)
    fixture.expire_all();assert fixture.get(Decision,1).estado=='PENDING'
    assert fixture.scalar(select(func.count()).select_from(EventoAuditoria))==1


@pytest.mark.parametrize('kind',['round_fk','decision_fk','unique_round','unique_decision','check_round','check_decision'])
def test_real_fk_unique_checks(approvals,kind):
    _,db,_,_=approvals
    if kind=='round_fk':db.add(Ronda(version_documento_id=999,numero_ronda=1,solicitada_por_id=1))
    elif kind=='decision_fk':db.add(Decision(ronda_aprobacion_id=999,aprobador_id=5))
    elif kind=='unique_round':db.add(Ronda(version_documento_id=1,numero_ronda=1,solicitada_por_id=1))
    elif kind=='unique_decision':db.add(Decision(ronda_aprobacion_id=1,aprobador_id=5))
    elif kind=='check_round':db.get(Ronda,1).estado='APPROVED'
    else:db.get(Decision,1).estado='APPROVED'
    with pytest.raises((IntegrityError,OperationalError)):db.commit()
    db.rollback();assert db.scalar(select(func.count()).select_from(Ronda))==4
    assert db.scalar(select(func.count()).select_from(Decision))==4


def test_old_repeatable_read_snapshot_next_round_number(approvals,mysql_factory):
    c,fixture,_,_=approvals;command(c,'cancelar');fixture.rollback()
    with mysql_factory() as old:
        actor=old.get(Usuario,1)
        assert old.scalar(select(func.max(Ronda.numero_ronda)).where(Ronda.version_documento_id==1))==1
        with mysql_factory() as newer:
            row=service.create(newer,newer.get(Usuario,1),RondaCreate(**body(version_documento_id=1)))
            assert row.numero_ronda==2
            service.command(newer,newer.get(Usuario,1),row.id,RondaCommand(estado_esperado=row.estado,updated_at_esperado=row.updated_at),'cancelar')
        row=service.create(old,actor,RondaCreate(**body(version_documento_id=1)))
        assert row.numero_ronda==3


def test_two_versions_share_audits_opposite_pivot_order_no_deadlock(approvals,mysql_factory):
    _,fixture,_,_=approvals
    # Opposite insertion order must not become the order in which audit locks
    # are acquired. Both versions share audits 1/2 but have different scopes.
    for audit,doc,version in [(2,1,1),(1,2,3)]:
        fixture.add(DocumentoAuditoria(auditoria_id=audit,documento_id=doc,version_documento_id=version,
            proposito='TEST',asociado_por_id=1))
    fixture.commit();stamps={i:fixture.get(Ronda,i).updated_at for i in [1,2]};fixture.rollback()
    barrier=Barrier(2)
    def mutate(id):
        with mysql_factory() as db:
            actor=db.get(Usuario,1);barrier.wait(timeout=10)
            return service.command(db,actor,id,RondaCommand(estado_esperado='PENDING',updated_at_esperado=stamps[id]),'iniciar').estado
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(mutate,[1,2]))
    assert results==['IN_REVIEW','IN_REVIEW']
    fixture.expire_all();assert fixture.scalar(select(func.count()).select_from(EventoAuditoria))==2


def test_audit_reassignment_while_waiting_revokes_internal_scope(approvals,mysql_factory):
    _,fixture,_,_=approvals;stamp=fixture.get(Ronda,1).updated_at;fixture.rollback()
    reached=Event();engine=mysql_factory.kw['bind']
    def observe(conn,cursor,stmt,*args):
        if 'FOR UPDATE' in stmt and 'FROM auditorias' in stmt and conn.info.get('scope_wait'):reached.set()
    event.listen(engine,'before_cursor_execute',observe)
    def mutate():
        with mysql_factory() as db:
            db.connection().info['scope_wait']=True;actor=db.get(Usuario,2)
            try:service.command(db,actor,1,RondaCommand(estado_esperado='PENDING',updated_at_esperado=stamp),'iniciar');return 200
            except HTTPException as exc:return exc.status_code
            finally:db.connection().info.pop('scope_wait',None)
    try:
        with mysql_factory() as owner,ThreadPoolExecutor(max_workers=1) as pool:
            audit=owner.scalar(select(Auditoria).where(Auditoria.id==1).with_for_update())
            pending=pool.submit(mutate);assert reached.wait(10);assert not pending.done()
            audit.responsable_id=6;owner.commit()
            assert pending.result(timeout=10)==404
    finally:event.remove(engine,'before_cursor_execute',observe)
    fixture.expire_all()
    assert fixture.get(Ronda,1).estado=='PENDING' and fixture.scalar(select(func.count()).select_from(EventoAuditoria))==0


def test_role_change_and_reassignment_during_wait_rechecks_actual_scope(approvals,mysql_factory):
    _,fixture,_,_=approvals
    fixture.get(Auditoria,1).responsable_id=1;fixture.commit()
    stamp=fixture.get(Ronda,1).updated_at;fixture.rollback()
    reached=Event();engine=mysql_factory.kw['bind']
    def observe(conn,cursor,stmt,*args):
        if 'FOR UPDATE' in stmt and 'FROM auditorias' in stmt and conn.info.get('role_scope_wait'):reached.set()
    event.listen(engine,'before_cursor_execute',observe)
    def mutate():
        with mysql_factory() as db:
            db.connection().info['role_scope_wait']=True;actor=db.get(Usuario,1)
            try:service.command(db,actor,1,RondaCommand(estado_esperado='PENDING',updated_at_esperado=stamp),'iniciar');return 200
            except HTTPException as exc:return exc.status_code
            finally:db.connection().info.pop('role_scope_wait',None)
    try:
        with mysql_factory() as owner,ThreadPoolExecutor(max_workers=1) as pool:
            audit=owner.scalar(select(Auditoria).where(Auditoria.id==1).with_for_update())
            actor=owner.scalar(select(Usuario).where(Usuario.id==1).with_for_update())
            pending=pool.submit(mutate);assert reached.wait(10);assert not pending.done()
            audit.responsable_id=6;actor.rol='AUDITOR_INTERNO';owner.commit()
            assert pending.result(timeout=10)==404
    finally:event.remove(engine,'before_cursor_execute',observe)
    fixture.expire_all()
    assert fixture.get(Ronda,1).estado=='PENDING' and fixture.scalar(select(func.count()).select_from(EventoAuditoria))==0
