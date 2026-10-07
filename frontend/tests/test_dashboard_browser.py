"""Actual Chrome: five effective roles, three widths, XSS and keyboard/link checks."""
import base64
import pytest
from test_auth_browser import chromium,evaluate
from test_auditorias_browser import go,wait


@pytest.mark.parametrize('role',['ADMIN','AUDITOR_INTERNO','AUDITOR_EXTERNO','RESPONSABLE_AREA','APROBADOR'])
@pytest.mark.parametrize('width,height',[(1440,1000),(390,844),(320,800)])
def test_executive_dashboard_responsive_keyboard_xss_links(frontend,tmp_path,role,width,height):
    client,api,_,_=frontend;api.role=role;api.audit['estado']='IN_REVIEW'
    payload='<script>window.dashboard_xss=1</script><img src=x onerror=window.dashboard_xss=2><svg onload=window.dashboard_xss=3>'
    api.finding['titulo']=payload;api.document['titulo']=payload
    base=str(client.base_url).rstrip('/')
    with chromium(tmp_path) as cdp:
        cdp('Emulation.setDeviceMetricsOverride',width=width,height=height,deviceScaleFactor=1,mobile=False)
        go(cdp,base+'/index.php?pagina=login',"!!document.getElementById('password')")
        evaluate(cdp,"document.getElementById('correo').value='browser@example.invalid';document.getElementById('password').value='correct';document.querySelector('.auth-form').requestSubmit()")
        wait(cdp,"!!document.querySelector('[data-kpi=documentos]')")
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        assert evaluate(cdp,'document.querySelectorAll("h1").length')==1
        assert evaluate(cdp,'typeof window.dashboard_xss')=='undefined'
        assert not evaluate(cdp,"document.documentElement.outerHTML.includes('"+api.token+"')")
        assert evaluate(cdp,"!!document.querySelector('[data-kpi=auditorias]')")==(role in {'ADMIN','AUDITOR_INTERNO','AUDITOR_EXTERNO'})
        if width==320:
            assert evaluate(cdp,"getComputedStyle(document.querySelector('.dashboard-metrics')).gridTemplateColumns.split(' ').length")==1
        # Focus the action and exercise actual Tab navigation and visible focus.
        evaluate(cdp,"document.querySelector('.page-heading a').focus()")
        cdp('Input.dispatchKeyEvent',type='keyDown',key='Tab',code='Tab',windowsVirtualKeyCode=9)
        cdp('Input.dispatchKeyEvent',type='keyUp',key='Tab',code='Tab',windowsVirtualKeyCode=9)
        assert evaluate(cdp,"document.activeElement.matches('a')")
        assert evaluate(cdp,"getComputedStyle(document.activeElement).outlineStyle")!='none'
        # Dynamic resource names must remain text, and links must lead to readable detail.
        assert evaluate(cdp,"document.querySelectorAll('.dashboard-items script,.dashboard-items img,.dashboard-items svg').length")==0
        (tmp_path/f'dashboard-{role}-{width}.png').write_bytes(base64.b64decode(cdp('Page.captureScreenshot',format='png',captureBeyondViewport=True)['data']))
        go(cdp,base+'/index.php?pagina=alertas',"!!document.getElementById('alert-severity')")
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        evaluate(cdp,"document.getElementById('alert-severity').focus()")
        cdp('Input.dispatchKeyEvent',type='keyDown',key='Tab',code='Tab',windowsVirtualKeyCode=9)
        cdp('Input.dispatchKeyEvent',type='keyUp',key='Tab',code='Tab',windowsVirtualKeyCode=9)
        assert evaluate(cdp,'document.activeElement.id')=='alert-type'
        evaluate(cdp,"document.getElementById('alert-severity').value='INFO';document.querySelector('.list-filters').requestSubmit()")
        wait(cdp,"location.search.includes('severidad=INFO') && !!document.querySelector('.dashboard-items a')")
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        assert evaluate(cdp,'typeof window.dashboard_xss')=='undefined'
        evaluate(cdp,"document.querySelector('.dashboard-items a').click()")
        wait(cdp,"location.search.includes('pagina=aprobacion&') && document.querySelector('h1')?.textContent === 'Ronda #1'")
        assert evaluate(cdp,'typeof window.dashboard_xss')=='undefined'
