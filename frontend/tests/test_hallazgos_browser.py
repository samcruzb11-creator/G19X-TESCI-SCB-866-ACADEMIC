"""Headless Chrome, desktop and narrow mobile: real PHP finding workflow."""
import base64
import pytest
from test_auth_browser import chromium,evaluate
from test_auditorias_browser import go,wait


@pytest.mark.parametrize('width,height',[(1440,1000),(390,844),(320,700)])
def test_findings_workflow_responsive_keyboard(frontend,tmp_path,width,height):
    c,api,_,_=frontend;api.audit['estado']='IN_PROGRESS'
    api.finding['titulo']='Long business finding title with supporting evidence and a clear resolution'
    base=str(c.base_url).rstrip('/')
    with chromium(tmp_path) as cdp:
        cdp('Emulation.setDeviceMetricsOverride',width=width,height=height,deviceScaleFactor=1,mobile=False)
        go(cdp,base+'/index.php?pagina=login',"!!document.getElementById('password')")
        evaluate(cdp,"document.getElementById('correo').value='browser@example.invalid';document.getElementById('password').value='correct';document.querySelector('.auth-form').requestSubmit()")
        wait(cdp,"location.search.includes('pagina=dashboard') && !!document.querySelector('.page-heading')")
        go(cdp,base+'/index.php?pagina=hallazgos',"!!document.querySelector('.finding-list')")
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        evaluate(cdp,"document.getElementById('finding-q').focus()")
        cdp('Input.dispatchKeyEvent',type='keyDown',key='Tab',code='Tab',windowsVirtualKeyCode=9)
        cdp('Input.dispatchKeyEvent',type='keyUp',key='Tab',code='Tab',windowsVirtualKeyCode=9)
        assert evaluate(cdp,'document.activeElement.id')=='finding-auditoria_id'
        go(cdp,base+'/index.php?pagina=hallazgo_nuevo&auditoria_id=1',"!!document.getElementById('titulo')")
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        assert evaluate(cdp,"[...document.querySelectorAll('.form-grid input,.form-grid select,.form-grid textarea')].every(e=>!!document.querySelector('label[for='+e.id+']'))")
        evaluate(cdp,"document.getElementById('titulo').value='Browser finding';document.getElementById('descripcion').value='Verified control gap';document.getElementById('categoria').value='Control';document.getElementById('titulo').form.requestSubmit()")
        wait(cdp,"location.search.includes('pagina=hallazgo&') && document.body.textContent.includes('Browser finding')")
        go(cdp,base+'/index.php?pagina=hallazgo_editar&id=1',"!!document.getElementById('titulo')")
        evaluate(cdp,"document.getElementById('titulo').value='Edited finding';document.getElementById('titulo').form.requestSubmit()")
        wait(cdp,"location.search.includes('pagina=hallazgo&') && document.body.textContent.includes('Edited finding')")
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        evaluate(cdp,"document.getElementById('evidencia_id').value='1';document.getElementById('evidencia_id').form.requestSubmit()")
        wait(cdp,"document.body.textContent.includes('Hallazgo actualizado correctamente')")
        for target in ('IN_PROGRESS','PENDING_VERIFICATION','CLOSED'):
            previous=api.finding['estado']
            evaluate(cdp,"document.getElementById('estado').value='"+target+"';document.getElementById('resolucion').value='Verified correction';document.getElementById('estado').form.requestSubmit()")
            wait(cdp,"!document.querySelector('input[name=estado_esperado][value="+previous+"]')")
            wait(cdp,"document.body.textContent.includes('Hallazgo actualizado correctamente')")
        assert not evaluate(cdp,"!!document.getElementById('estado')")
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        assert not evaluate(cdp,"document.documentElement.outerHTML.includes('"+api.token+"')")
        (tmp_path/f'hallazgo-{width}.png').write_bytes(base64.b64decode(cdp('Page.captureScreenshot',format='png')['data']))
