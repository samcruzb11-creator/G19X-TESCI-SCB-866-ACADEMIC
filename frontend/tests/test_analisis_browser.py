"""Actual Chrome, effective roles, all requested widths and safe navigation."""
import pytest
from test_auth_browser import chromium,evaluate
from test_auditorias_browser import go,wait
from test_analisis import install


@pytest.mark.parametrize('role',['ADMIN','AUDITOR_INTERNO','AUDITOR_EXTERNO','RESPONSABLE_AREA','APROBADOR'])
@pytest.mark.parametrize('width,height',[(1440,1000),(390,844),(320,800)])
def test_analysis_responsive_keyboard_filters_xss_links(frontend,tmp_path,role,width,height):
    client,api,_,_=frontend;api.role=role
    payload='<script>window.analysis_xss=1</script><img src=x onerror=window.analysis_xss=2><svg onload=window.analysis_xss=3>'
    install(api,payload)
    base=str(client.base_url).rstrip('/')
    with chromium(tmp_path) as cdp:
        cdp('Emulation.setDeviceMetricsOverride',width=width,height=height,deviceScaleFactor=1,mobile=False)
        go(cdp,base+'/index.php?pagina=login',"!!document.getElementById('password')")
        evaluate(cdp,"document.getElementById('correo').value='browser@example.invalid';document.getElementById('password').value='correct';document.querySelector('.auth-form').requestSubmit()")
        wait(cdp,"!!document.querySelector('[data-kpi=documentos]')")
        go(cdp,base+'/index.php?pagina=analisis',"!!document.getElementById('analysis-type')")
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        assert evaluate(cdp,'typeof window.analysis_xss')=='undefined'
        assert evaluate(cdp,"document.querySelectorAll('.analysis-items script,.analysis-items img,.analysis-items svg').length")==0
        assert not evaluate(cdp,"document.documentElement.outerHTML.includes('"+api.token+"')")
        evaluate(cdp,"document.getElementById('analysis-severity').focus()")
        cdp('Input.dispatchKeyEvent',type='keyDown',key='Tab',code='Tab',windowsVirtualKeyCode=9)
        cdp('Input.dispatchKeyEvent',type='keyUp',key='Tab',code='Tab',windowsVirtualKeyCode=9)
        assert evaluate(cdp,'document.activeElement.id')=='analysis-type'
        assert evaluate(cdp,'getComputedStyle(document.activeElement).outlineStyle')!='none'
        evaluate(cdp,"document.querySelector('.analysis-items summary').focus();document.querySelector('.analysis-items details').open=true")
        assert evaluate(cdp,"document.querySelector('.analysis-items details').textContent.includes('7E:DUPLICATE_HASH:1')")
        evaluate(cdp,"document.getElementById('analysis-type').value='DUPLICATE_HASH';document.querySelector('.list-filters').requestSubmit()")
        wait(cdp,"location.search.includes('tipo=DUPLICATE_HASH') && !!document.querySelector('.analysis-items')")
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        evaluate(cdp,"document.querySelector('.analysis-actions a').click()")
        wait(cdp,"location.search.includes('pagina=documento&') && !!document.querySelector('h1')")
        assert evaluate(cdp,'typeof window.analysis_xss')=='undefined'
