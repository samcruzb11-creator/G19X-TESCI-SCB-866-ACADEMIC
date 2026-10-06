"""Shared lifecycle/IDOR regression plus actual MySQL row-lock concurrency."""
from tests_unit.test_auditoria_unit import *  # noqa: F403
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from fastapi import HTTPException
from sqlalchemy import select, func
from app.models.entities import Usuario, Auditoria, EventoAuditoria
from app.schemas.auditoria import AuditoriaTransition
from app.services import auditoria_service as service

MYSQL_RBAC = True


@pytest.mark.parametrize('initial,targets',[('PLANNED',['IN_PROGRESS','IN_PROGRESS']),('IN_REVIEW',['IN_PROGRESS','COMPLETED'])])
def test_real_concurrent_transition_one_commit_one_conflict(mysql_factory, clean_temporary_schema, initial, targets):
    with mysql_factory() as db:
        db.add_all([Usuario(id=1,nombre='Admin',correo='a@example.invalid',correo_normalizado='a@example.invalid',password_hash='unused',rol='ADMIN',activo=True),
                    Usuario(id=2,nombre='Auditor',correo='b@example.invalid',correo_normalizado='b@example.invalid',password_hash='unused',rol='AUDITOR_INTERNO',activo=True)])
        db.flush();row=Auditoria(nombre='Race',codigo='RACE',alcance='Scope',responsable_id=2,created_by_id=1,estado=initial)
        db.add(row);db.commit();audit_id=row.id;stamp=row.updated_at
    barrier=Barrier(2)
    def change(target):
        with mysql_factory() as db:
            user=db.get(Usuario,1)
            barrier.wait(timeout=10)
            try:
                service.transition(db,user,audit_id,AuditoriaTransition(estado=target,estado_esperado=initial,updated_at_esperado=stamp))
                return 200
            except HTTPException as exc:return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(change,targets))==[200,409]
    with mysql_factory() as db:
        assert db.get(Auditoria,audit_id).estado in targets
        assert db.scalar(select(func.count()).select_from(EventoAuditoria))==1


def test_005_downgrade_refuses_review_rows_without_ddl_or_data_change(rbac,mysql_factory):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    c,db,_,_=rbac;db.get(Auditoria,1).estado='IN_REVIEW';db.commit()
    root=Path(__file__).resolve().parents[1];cfg=Config(str(root/'alembic.ini'))
    cfg.set_main_option('script_location',str(root/'app/db/migrations'))
    with mysql_factory.kw['bind'].connect() as connection:
        ddl=connection.exec_driver_sql('SHOW CREATE TABLE auditorias').one()[1];connection.commit()
        cfg.attributes['connection']=connection
        with pytest.raises(RuntimeError,match='Downgrade bloqueado'):command.downgrade(cfg,'004')
        assert connection.exec_driver_sql('SHOW CREATE TABLE auditorias').one()[1]==ddl
        assert connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()=='005'
        assert connection.exec_driver_sql('SELECT estado FROM auditorias WHERE id=1').scalar_one()=='IN_REVIEW'


def test_activation_checks_latest_active_responsible_not_repeatable_read_snapshot(rbac,mysql_factory):
    c,fixture_db,_,_=rbac
    with mysql_factory() as first:
        admin=first.get(Usuario,1)
        row=first.get(Auditoria,1)  # Establish the older consistent-read snapshot.
        stamp=row.updated_at
        with mysql_factory() as other:
            other.get(Usuario,2).activo=False
            other.commit()
        with pytest.raises(HTTPException) as error:
            service.transition(first,admin,1,AuditoriaTransition(estado='IN_PROGRESS',estado_esperado='PLANNED',updated_at_esperado=stamp))
        assert error.value.status_code==404
    fixture_db.expire_all()
    assert fixture_db.get(Auditoria,1).estado=='PLANNED'
    assert fixture_db.scalar(select(func.count()).select_from(EventoAuditoria))==0
