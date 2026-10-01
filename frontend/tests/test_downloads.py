from pathlib import Path
import subprocess
import pytest
from conftest import login, PHP, ROOT


@pytest.mark.parametrize('page,path',[
    ('documento&id=1&accion=descargar&version_id=1','/api/v1/documentos/1/versiones/1/descargar'),
    ('evidencia&id=1&accion=descargar','/api/v1/evidencias/1/descargar'),
])
@pytest.mark.parametrize('status',[200,401,403,404])
def test_authenticated_download(frontend,page,path,status):
    c, api, private, _ = frontend
    login(c)
    sid=c.cookies.get('PHPSESSID')
    if status!=200: api.overrides['GET',path]=(status,{'detail':'SECRET internal'}, {})
    r=c.get('/index.php?pagina='+page)
    assert r.status_code==(303 if status==401 else status)
    req=next(req for req in reversed(api.requests) if req['path']==path)
    assert req['headers']['Authorization']=='Bearer '+api.token
    assert api.token not in r.text and 'SECRET' not in r.text
    if status==200:
        assert r.content==api.content
        assert r.headers['content-type']=='application/pdf'
        assert 'report.pdf' in r.headers['content-disposition']
    elif status==401:
        assert c.cookies.get('PHPSESSID')!=sid
        assert 'La sesión expiró.' in c.get(r.headers['location']).text
    else: assert c.cookies.get('PHPSESSID')==sid
    assert not [p for p in private.iterdir() if p.is_file()], 'Download temporary leaked'


def test_large_download_filename_sanitized_and_closed(frontend):
    c,api,private,_=frontend
    login(c)
    # Larger than the PHP memory_limit set by the fixture (16 MiB).
    api.content=b'z'*(20*1024*1024)
    api.file_headers['Content-Disposition']="attachment; filename*=UTF-8''..%2F..%2Freport%0D%0AX-Evil%3Ayes.pdf"
    r=c.get('/index.php?pagina=documento&id=1&accion=descargar&version_id=1')
    assert r.status_code==200 and r.content==api.content
    disposition=r.headers['content-disposition']
    assert '../' not in disposition and '%0D' not in disposition and '%0A' not in disposition
    assert 'x-evil' not in r.headers
    assert not [p for p in private.iterdir() if p.is_file()]


def test_header_sanitizer_rejects_invalid_mime():
    source=(ROOT/'frontend/services/download_response.php').as_posix()
    script=f'''require '{source}';
    $safe = download_metadata(['content-type' => "text/plain\\r\\nX-Evil: yes"], ['nombre_original' => '..']);
    echo json_encode($safe);'''
    result=subprocess.run([PHP,'-r',script],capture_output=True,text=True,check=True)
    import json
    assert json.loads(result.stdout)=={'filename':'archivo','mime':'application/octet-stream'}
