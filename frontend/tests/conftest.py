"""Real PHP HTTP requests against an isolated API double, never the project API."""
from contextlib import contextmanager
from copy import deepcopy
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit
import html
import json
import os
import re
import shutil
import socket
import subprocess
import time

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
PHP = os.environ.get('PHP_TEST_BINARY', r'C:\xampp\php\php.exe')
LEGACY = {'creador_id', 'editor_id', 'subido_por_id', 'registrada_por_id', 'created_by_id'}


def csrf(response):
    match = re.search(r'name="csrf_token" value="([a-f0-9]+)"', response.text)
    assert match, 'CSRF field missing'
    return html.unescape(match[1])


@contextmanager
def php_server(directory, api_url):
    """Copy only frontend code, with a test-only URL and private temp directory."""
    directory.mkdir(parents=True, exist_ok=True)
    web = directory / 'web'
    private = directory / 'private'
    private.mkdir()
    shutil.copytree(ROOT / 'frontend', web, ignore=shutil.ignore_patterns('tests', '__pycache__'))
    config = web / 'config/config.php'
    config.write_text(config.read_text(encoding='utf-8').replace("'http://127.0.0.1:8000'", repr(api_url)), encoding='utf-8')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with (directory / 'php.log').open('wb') as log:
        process = subprocess.Popen([PHP, '-d', f'sys_temp_dir={private}', '-d', 'memory_limit=16M',
                                    '-S', f'127.0.0.1:{port}', '-t', str(web)],
                                   stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        client = httpx.Client(base_url=f'http://127.0.0.1:{port}', follow_redirects=False, timeout=15)
        try:
            deadline = time.monotonic() + 10
            while True:
                try:
                    response = client.get('/index.php?pagina=login')
                    assert response.status_code == 200, response.text
                    break
                except httpx.TransportError:
                    if time.monotonic() >= deadline or process.poll() is not None:
                        raise AssertionError('Isolated PHP server did not start') from None
                    time.sleep(.05)
            yield client, private, web
        finally:
            client.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


class FakeAPI:
    def __init__(self):
        self.role = 'ADMIN'
        self.name = 'Test User'
        self.token = 'test-access-token-server-only'
        self.valid = True
        self.requests = []
        self.overrides = {}
        self.drop = set()
        self.content = b'authorized-file'
        self.file_headers = {'Content-Type': 'application/pdf', 'Content-Disposition': 'attachment; filename="report.pdf"'}
        self.version = dict(id=1, documento_id=1, numero_version=1, nombre_original='report.pdf',
                            mime_type='application/pdf', tamano_bytes=15, sha256='a'*64,
                            subido_por_id=7, created_at='2026-10-01T00:00:00')
        self.document = dict(id=1, codigo='DOC1', titulo='Test document', descripcion='Description',
                             tipo='TEST', estado='ACTIVE', area_id=1, responsable_id=7,
                             created_by_id=7, version_vigente_id=1, version_vigente=self.version,
                             created_at='2026-10-01T00:00:00', updated_at='2026-10-01T00:00:00')
        self.audit = dict(id=1, codigo='AUD1', nombre='Test audit', alcance='Scope', estado='PLANNED',
                         responsable_id=7, created_by_id=7, fecha_inicio_prevista=None, fecha_fin_prevista=None,
                         updated_at='2026-10-01T00:00:00', responsable=dict(id=7,nombre='Test User'),areas=[])
        self.evidence = dict(id=1, auditoria_id=1, documento_id=1, version_documento_id=1, titulo='Test evidence',
                            tipo='FILE', registrada_por_id=7, nombre_original='evidence.pdf', mime_type='application/pdf')

        self.finding = dict(id=1,auditoria_id=1,numero=1,titulo='Test finding',descripcion='Verified issue',categoria='Control',severidad='HIGH',estado='OPEN',responsable_id=7,responsable=dict(id=7,nombre='Test User'),fecha_limite=None,resolucion=None,created_by_id=7,updated_by_id=None,created_at='2026-10-01T00:00:00',updated_at='2026-10-01T00:00:00',detectado_en='2026-10-01T00:00:00',evidencias_count=1)

    def answer(self, request):
        self.requests.append(request)
        path, method = request['path'], request['method']
        if (method, path) in self.overrides:
            return self.overrides[method, path]
        if path == '/api/v1/auth/login':
            if request['json']['password'] != 'correct' or request['json']['correo'] == 'inactive@example.invalid':
                return 401, {'detail': 'Invalid credentials'}, {}
            self.valid = True
            return 200, dict(access_token=self.token, token_type='bearer', expires_in=900), {}
        if not self.valid or request['headers'].get('Authorization') != 'Bearer ' + self.token:
            return 401, {'detail': 'Session invalid'}, {}
        if path == '/api/v1/auth/me':
            return 200, dict(id=7, nombre=self.name, rol=self.role, correo='not-stored@example.invalid'), {}
        if path == '/api/v1/auth/logout':
            self.valid = False
            return 204, None, {}
        if path.startswith('/api/v1/aprobaciones'):
            return self.answer_approvals(request)
        if path.startswith('/api/v1/dashboard/'):
            return self.answer_dashboard(request)
        if path.endswith('/descargar'):
            return 200, self.content, self.file_headers
        if method == 'PATCH' and path == '/api/v1/auditorias/1':
            self.audit.update({k:v for k,v in request['json'].items() if k != 'updated_at_esperado'})
            self.audit['updated_at'] = '2026-10-01T00:00:01'
            return 200, self.audit, {}
        if method == 'POST' and path == '/api/v1/auditorias/1/estado':
            self.audit['estado'] = request['json']['estado']
            self.audit['updated_at'] = '2026-10-01T00:00:02'
            return 200, self.audit, {}
        if path == '/api/v1/hallazgos' and method=='POST':
            self.finding.update(request['json'])
            return 201,self.finding,{}
        if path == '/api/v1/hallazgos/1' and method=='PATCH':
            self.finding.update({k:v for k,v in request['json'].items() if k!='updated_at_esperado'})
            self.finding['updated_at']='2026-10-01T00:00:01'
            return 200,self.finding,{}
        if path == '/api/v1/hallazgos/1/estado' and method=='POST':
            self.finding['estado']=request['json']['estado']
            self.finding['updated_at']='2026-10-01T00:00:02'
            return 200,self.finding,{}
        if path == '/api/v1/hallazgos/1/evidencias':
            return (201,self.finding,{}) if method=='POST' else (200,[self.evidence],{'X-Total-Count':'1'})
        if path == '/api/v1/hallazgos': return 200,[self.finding],{'X-Total-Count':'1'}
        if path == '/api/v1/hallazgos/1': return 200,self.finding,{}
        if method == 'POST':
            if path.endswith('/versiones'): return 201, self.version, {}
            if path == '/api/v1/documentos': return 201, self.document, {}
            if path == '/api/v1/auditorias': return 201, self.audit, {}
            return 201, self.evidence, {}
        if path == '/api/v1/areas': return 200, [dict(id=1,nombre='Area',codigo='A1',activa=True)], {}
        if path == '/api/v1/usuarios': return 200, [dict(id=7,nombre='Test User',activo=True),dict(id=8,nombre='Other auditor',activo=True)], {}
        if path == '/api/v1/documentos': return 200, [self.document], {}
        if path.endswith('/historial'): return 200, [], {}
        if path.endswith('/versiones'): return 200, [self.version], {}
        if path.startswith('/api/v1/documentos/'): return 200, self.document, {}
        if path == '/api/v1/auditorias': return 200, [self.audit], {'X-Total-Count':'1'}
        if path == '/api/v1/auditorias/1': return 200, self.audit, {}
        if path == '/api/v1/evidencias': return 200, [self.evidence], {}
        if path.startswith('/api/v1/evidencias/'): return 200, self.evidence, {}
        return 404, {}, {}

    def answer_dashboard(self, request):
        from urllib.parse import parse_qs
        self.answer_approvals(dict(path='/api/v1/aprobaciones',method='GET'))
        auditor = self.role in {'ADMIN','AUDITOR_INTERNO','AUDITOR_EXTERNO'}
        def dist(states, state):
            return dict(total=1,por_estado={s:int(s==state) for s in (*states,'DESCONOCIDO')})
        def ratio(n,d,applicable=True):
            return dict(numerador=n,denominador=d,porcentaje=100*n/d if applicable and d else None,
                        estado='NOT_APPLICABLE' if not applicable else 'OK' if d else 'NO_DATA')
        indicators=dict(
            auditorias=dist(('PLANNED','IN_PROGRESS','IN_REVIEW','COMPLETED','CANCELLED'),self.audit['estado']) if auditor else None,
            hallazgos=dist(('OPEN','IN_PROGRESS','PENDING_VERIFICATION','CLOSED','ACCEPTED_RISK'),self.finding['estado']) if auditor else None,
            aprobaciones=dist(('PENDING','IN_REVIEW','APPROVED','REJECTED','CHANGES_REQUESTED','CANCELLED'),self.approval['estado']),
            decisiones={**dist(('PENDING','APPROVED','REJECTED','CHANGES_REQUESTED'),self.approval_decision['estado']),
                        'resueltas':int(self.approval_decision['estado']!='PENDING'),
                        'pendientes_propias':int(self.approval_decision['estado']=='PENDING') if self.role=='APROBADOR' else None},
            documentos=dict(total=1,versiones=1,sin_version=None if self.role=='APROBADOR' else 0),
            evidencias=dist(('FILE','REFERENCE','NOTE','OTHER'),self.evidence['tipo']) if auditor else None,
            auditorias_completadas=ratio(int(self.audit['estado']=='COMPLETED'),1,auditor),
            hallazgos_cerrados=ratio(int(self.finding['estado']=='CLOSED'),1,auditor),
            rondas_resueltas=ratio(int(self.approval['estado'] in {'APPROVED','REJECTED','CHANGES_REQUESTED'}),1),
            documentos_con_version=ratio(1,1,self.role!='APROBADOR'))
        alerts=[]
        if auditor and self.audit['estado'] in {'IN_PROGRESS','IN_REVIEW'} and self.finding['estado'] in {'OPEN','IN_PROGRESS','PENDING_VERIFICATION'}:
            alerts.append(dict(clave='HALLAZGO_PENDIENTE:hallazgo:1',tipo='HALLAZGO_PENDIENTE',severidad='WARNING',
                titulo='Hallazgo sin resolver',descripcion='Hallazgo pendiente en auditoría activa.',nombre=self.finding['titulo'],
                recurso='hallazgo',recurso_id=1,fecha='2026-10-01T00:00:00',destino=dict(pagina='hallazgo',id=1)))
        if self.approval['estado'] in {'PENDING','IN_REVIEW'}:
            alerts.append(dict(clave='RONDA_PENDIENTE:aprobacion:1',tipo='RONDA_PENDIENTE',severidad='INFO',
                titulo='Ronda pendiente registrada',descripcion='Consulta las acciones disponibles en el detalle.',nombre=self.document['titulo'],
                recurso='aprobacion',recurso_id=1,fecha='2026-10-01T00:00:00',destino=dict(pagina='aprobacion',id=1)))
        query=parse_qs(request.get('query',''))
        for key in ('tipo','severidad'):
            if key in query:alerts=[a for a in alerts if a[key]==query[key][0]]
        limit=int(query.get('limit',['10'])[0]);offset=int(query.get('offset',['0'])[0])
        alert_page=dict(total=len(alerts),limit=limit,offset=offset,items=alerts[offset:offset+limit])
        activity=dict(total=0,limit=limit,offset=offset,items=[])
        summary=dict(generado_en='2026-10-01T00:00:00',indicadores=indicators,alertas=alert_page,actividad=activity)
        data={'resumen':summary,'indicadores':indicators,'alertas':alert_page,'actividad':activity}[request['path'].rsplit('/',1)[-1]]
        return 200,data,{'Cache-Control':'no-store'}

    def answer_approvals(self, request):
        if not hasattr(self, 'approval'):
            self.approval=dict(id=1,numero_ronda=1,estado='PENDING',documento_id=1,
                documento_titulo='Test document',version_documento_id=1,numero_version=1,
                solicitada_por=dict(id=7,nombre='Test User'),solicitada_en='2026-10-01T00:00:00',
                resuelta_en=None,created_at='2026-10-01T00:00:00',updated_at='2026-10-01T00:00:00',
                decisiones_count=1,pendientes_count=1,mi_decision=None,puede_decidir=False,puede_gestionar=True)
            self.approval_decision=dict(id=1,ronda_aprobacion_id=1,aprobador_id=7,
                aprobador=dict(id=7,nombre='Test User'),estado='PENDING',comentario=None,
                asignada_en='2026-10-01T00:00:00',decidida_en=None,updated_at='2026-10-01T00:00:00')
        path,method=request['path'],request['method']
        if path=='/api/v1/aprobaciones/aprobadores':return 200,[dict(id=7,nombre='Test User'),dict(id=8,nombre='Other approver')],{'X-Total-Count':'2'}
        if path=='/api/v1/aprobaciones/recursos':return 200,[dict(documento_id=1,documento_titulo='Test document',version_documento_id=1,numero_version=1)],{'X-Total-Count':'1'}
        if path.endswith('/historial'):return 200,[],{'X-Total-Count':'0'}
        if path.endswith('/decisiones'):return 200,[self.approval_decision],{'X-Total-Count':'1'}
        if method=='POST':
            if path.endswith('/iniciar'):self.approval['estado']='IN_REVIEW'
            elif path.endswith('/cancelar'):self.approval['estado']='CANCELLED'
            elif path.endswith('/decision'):
                self.approval_decision.update(estado=request['json']['estado'],comentario=request['json'].get('comentario'),decidida_en='2026-10-01T00:00:01')
                self.approval.update(estado=request['json']['estado'],pendientes_count=0,resuelta_en='2026-10-01T00:00:01')
            self.approval['updated_at']='2026-10-01T00:00:01'
        active=self.approval['estado'] in {'PENDING','IN_REVIEW'} and self.audit['estado'] not in {'COMPLETED','CANCELLED'}
        self.approval['puede_gestionar']=self.role in {'ADMIN','AUDITOR_INTERNO'} and active
        self.approval['puede_decidir']=self.role=='APROBADOR' and active and self.approval['estado']=='IN_REVIEW' and self.approval_decision['estado']=='PENDING'
        self.approval['mi_decision']=self.approval_decision if self.role=='APROBADOR' else None
        if path=='/api/v1/aprobaciones' and method=='GET':return 200,[self.approval],{'X-Total-Count':'1'}
        return (201 if path=='/api/v1/aprobaciones' and method=='POST' else 200),self.approval,{}


@pytest.fixture
def frontend(tmp_path):
    state = FakeAPI()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def handle_request(self):
            url = urlsplit(self.path)
            if url.path in state.drop:
                self.close_connection = True
                self.connection.close()
                return
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            request = dict(method=self.command,path=url.path,query=url.query,headers=dict(self.headers),json=None,fields={})
            content_type = self.headers.get('Content-Type', '')
            if content_type.startswith('application/json') and body:
                request['json'] = json.loads(body)
            elif content_type.startswith('multipart/form-data'):
                message = BytesParser(policy=default).parsebytes(b'Content-Type: '+content_type.encode()+b'\r\n\r\n'+body)
                assert message.is_multipart(), 'Missing multipart boundary'
                for part in message.iter_parts():
                    request['fields'][part.get_param('name', header='content-disposition')] = part.get_payload(decode=True)
            status, data, headers = state.answer(request)
            payload = data if isinstance(data,bytes) else b'' if data is None else json.dumps(data).encode()
            self.send_response(status)
            for name, value in headers.items(): self.send_header(name,value)
            if 'Content-Type' not in headers: self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = handle_request
        do_POST = handle_request
        do_PATCH = handle_request

    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        with php_server(tmp_path / 'php',f'http://127.0.0.1:{server.server_port}') as (client,private,web):
            yield client,state,private,web
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)


def login(client, role=None, state=None):
    if role is not None: state.role = role
    page = client.get('/index.php?pagina=login')
    return client.post('/index.php?pagina=login',data={'correo':'user@example.invalid','password':'correct','csrf_token':csrf(page)})


@pytest.fixture
def turnstile_frontend(monkeypatch, request):
    # Official public test sitekey; every actual widget script is stubbed offline.
    monkeypatch.setenv('TURNSTILE_SITE_KEY', '1x00000000000000000000AA')
    return request.getfixturevalue('frontend')
