"""PHP audit pages and transport: local double, CSRF, errors and scoped pagination."""
from urllib.parse import parse_qs
import re
import pytest
from conftest import csrf, login


def mutation(api):return [r for r in api.requests if r['method'] in {'POST','PATCH'} and r['path'].startswith('/api/v1/auditorias')]


def test_list_passes_filters_and_page_to_api(frontend):
    c,api,_,_=frontend;login(c)
    api.overrides['GET','/api/v1/auditorias']=(200,[api.audit],{'X-Total-Count':'61'})
    r=c.get('/index.php?pagina=auditorias&p=2&q=Test&estado=PLANNED&area_id=1&responsable_id=7&inicio_desde=2026-01-01&orden=-id')
    assert r.status_code==200 and '61 registros' in r.text and 'Siguiente' in r.text and 'Anterior' in r.text
    request=next(x for x in reversed(api.requests) if x['path']=='/api/v1/auditorias')
    params=parse_qs(request['query']);assert params['limit']==['20'] and params['offset']==['20']
    assert params['q']==['Test'] and params['estado']==['PLANNED'] and params['area_id']==['1']
    assert params['orden']==['-id'] and params['responsable_id']==['7']
    assert len([x for x in api.requests if x['path']=='/api/v1/auditorias'])==1


def test_detail_is_direct_resource_and_history(frontend):
    c,api,_,_=frontend;login(c)
    r=c.get('/index.php?pagina=auditoria&id=1')
    assert r.status_code==200 and 'Activar auditoría' in r.text and 'Editar auditoría' in r.text
    assert any(x['path']=='/api/v1/auditorias/1' for x in api.requests)
    assert not any(x['path'] in {'/api/v1/auditorias','/api/v1/usuarios'} for x in api.requests)


@pytest.mark.parametrize('role',['AUDITOR_INTERNO','AUDITOR_EXTERNO'])
def test_read_only_visual_controls_and_direct_mutation_denied(frontend,role):
    c,api,_,_=frontend;api.role=role;login(c)
    r=c.get('/index.php?pagina=auditoria&id=1');assert r.status_code==200
    assert 'Activar auditoría' not in r.text and 'Editar auditoría' not in r.text
    assert c.get('/index.php?pagina=auditoria_editar&id=1').status_code==403
    assert c.post('/index.php?pagina=auditoria&id=1',data={'estado':'COMPLETED','csrf_token':csrf(r)}).status_code==403
    assert not mutation(api)


@pytest.mark.parametrize('page',['auditoria_nueva','auditoria_editar&id=1','auditoria&id=1'])
def test_csrf_blocks_all_mutations(frontend,page):
    c,api,_,_=frontend;login(c)
    r=c.post('/index.php?pagina='+page,data={'csrf_token':'bad','codigo':'NEW','nombre':'New','alcance':'Scope','responsable_id':7,'estado':'IN_PROGRESS'})
    assert r.status_code==403 and not mutation(api)


def test_edit_uses_patch_preserves_submitted_version_and_no_actor(frontend):
    c,api,_,_=frontend;login(c);form=c.get('/index.php?pagina=auditoria_editar&id=1')
    assert form.status_code==200
    r=c.post('/index.php?pagina=auditoria_editar&id=1',data={'csrf_token':csrf(form),'nombre':'Edited','alcance':'Scope','responsable_id':'7','fecha_inicio_prevista':'','fecha_fin_prevista':'','updated_at_esperado':'2025-01-01T00:00:00','created_by_id':999,'estado':'COMPLETED','codigo':'MASS'})
    assert r.status_code==303
    request=mutation(api)[0];assert request['method']=='PATCH' and request['path']=='/api/v1/auditorias/1'
    assert request['json']['updated_at_esperado']=='2025-01-01T00:00:00'
    assert set(request['json'])=={'nombre','alcance','responsable_id','fecha_inicio_prevista','fecha_fin_prevista','updated_at_esperado'}
    assert request['headers']['Authorization']=='Bearer '+api.token


def test_state_command_uses_csrf_expected_state_and_timestamp(frontend):
    c,api,_,_=frontend;login(c);detail=c.get('/index.php?pagina=auditoria&id=1')
    r=c.post('/index.php?pagina=auditoria&id=1',data={'csrf_token':csrf(detail),'estado':'IN_PROGRESS','estado_esperado':'PLANNED','updated_at_esperado':api.audit['updated_at'],'actor_id':999})
    assert r.status_code==303
    assert mutation(api)[0]['json']=={'estado':'IN_PROGRESS','estado_esperado':'PLANNED','updated_at_esperado':'2026-10-01T00:00:00'}


@pytest.mark.parametrize('status',[401,403,404,409,422,503])
def test_state_errors_sanitized_no_false_success(frontend,status):
    c,api,_,_=frontend;login(c);form=c.get('/index.php?pagina=auditoria&id=1')
    api.overrides['POST','/api/v1/auditorias/1/estado']=(status,{'detail':'SECRET SQL /server/path'}, {})
    r=c.post('/index.php?pagina=auditoria&id=1',data={'csrf_token':csrf(form),'estado':'IN_PROGRESS','estado_esperado':'PLANNED','updated_at_esperado':api.audit['updated_at']})
    assert r.status_code==(303 if status==401 else status) and 'SECRET' not in r.text
    assert 'Estado actualizado correctamente' not in r.text


@pytest.mark.parametrize('state',['IN_REVIEW','COMPLETED','CANCELLED'])
def test_frozen_edit_hidden_and_direct_page_rejected(frontend,state):
    c,api,_,_=frontend;login(c);api.audit['estado']=state
    r=c.get('/index.php?pagina=auditoria&id=1');assert r.status_code==200 and 'Editar auditoría' not in r.text
    assert c.get('/index.php?pagina=auditoria_editar&id=1').status_code==409
    if state=='IN_REVIEW':assert 'Cerrar auditoría' in r.text and 'Regresar a activa' in r.text
    else:assert 'Registrar archivo' not in r.text and 'Esta auditoría es terminal' in r.text


def test_validation_retains_escaped_nonsensitive_values(frontend):
    c,api,_,_=frontend;login(c);form=c.get('/index.php?pagina=auditoria_nueva')
    r=c.post('/index.php?pagina=auditoria_nueva',data={'csrf_token':csrf(form),'codigo':'X','nombre':'<script>bad</script>','alcance':'','responsable_id':7})
    assert r.status_code==422 and '&lt;script&gt;' in r.text and '<script>bad</script>' not in r.text
    assert not mutation(api)


@pytest.mark.parametrize('query',['p=0','p=502','p[]=1','q[]=x'])
def test_abusive_php_filters_rejected(frontend,query):
    c,_,_,_=frontend;login(c)
    assert c.get('/index.php?pagina=auditorias&'+query).status_code==422


@pytest.mark.parametrize('status',[401,403,404,422,503])
def test_list_and_detail_api_errors(frontend,status):
    c,api,_,_=frontend;login(c)
    api.overrides['GET','/api/v1/auditorias']=(status,{'detail':'SECRET SQL'}, {})
    r=c.get('/index.php?pagina=auditorias');assert r.status_code==(303 if status==401 else status) and 'SECRET' not in r.text


def test_no_user_catalog_for_external_reader(frontend):
    c,api,_,_=frontend;api.role='AUDITOR_EXTERNO';login(c)
    assert c.get('/index.php?pagina=auditorias').status_code==200
    assert not any(x['path']=='/api/v1/usuarios' for x in api.requests)
