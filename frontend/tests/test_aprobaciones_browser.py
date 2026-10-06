"""Actual Chrome/PHP approval workflow at all requested viewport sizes."""
import base64
import pytest
from test_auth_browser import chromium,evaluate
from test_auditorias_browser import go,wait


@pytest.mark.parametrize('width,height',[(1440,1000),(390,844),(320,700)])
def test_approval_workflow_responsive_keyboard(frontend,tmp_path,width,height):
    c,api,_,_=frontend;api.audit['estado']='IN_REVIEW'
    base=str(c.base_url).rstrip('/')
    with chromium(tmp_path) as cdp:
        cdp('Emulation.setDeviceMetricsOverride',width=width,height=height,deviceScaleFactor=1,mobile=False)
        go(cdp,base+'/index.php?pagina=login',"!!document.getElementById('password')")
        evaluate(cdp,"document.getElementById('correo').value='browser@example.invalid';document.getElementById('password').value='correct';document.querySelector('.auth-form').requestSubmit()")
        wait(cdp,"location.search.includes('pagina=dashboard') && !!document.querySelector('.page-heading')")
        go(cdp,base+'/index.php?pagina=aprobaciones',"!!document.querySelector('.approval-list')")
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        evaluate(cdp,"document.getElementById('approval-q').focus()")
        cdp('Input.dispatchKeyEvent',type='keyDown',key='Tab',code='Tab',windowsVirtualKeyCode=9)
        cdp('Input.dispatchKeyEvent',type='keyUp',key='Tab',code='Tab',windowsVirtualKeyCode=9)
        assert evaluate(cdp,'document.activeElement.id')=='approval-documento_id'
        go(cdp,base+'/index.php?pagina=aprobacion_nueva&auditoria_id=1',"!!document.querySelector('.approval-create')")
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        evaluate(cdp,"document.getElementById('version_documento_id').value='1';document.getElementById('approver-7').checked=true;document.querySelector('.approval-create').requestSubmit()")
        wait(cdp,"location.search.includes('pagina=aprobacion&') && document.body.textContent.includes('Ronda creada correctamente')")
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        evaluate(cdp,"document.querySelector('input[name=accion][value=iniciar]').form.requestSubmit()")
        wait(cdp,"document.body.textContent.includes('En revisión') && !document.querySelector('input[name=accion][value=iniciar]')")
        api.role='APROBADOR'
        go(cdp,base+'/index.php?pagina=aprobaciones&pendientes_propias=true',"document.body.textContent.includes('Revisar y decidir')")
        go(cdp,base+'/index.php?pagina=aprobacion&id=1',"!!document.querySelector('.approval-vote')")
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        evaluate(cdp,"document.getElementById('decision-estado').focus()")
        cdp('Input.dispatchKeyEvent',type='keyDown',key='Tab',code='Tab',windowsVirtualKeyCode=9)
        cdp('Input.dispatchKeyEvent',type='keyUp',key='Tab',code='Tab',windowsVirtualKeyCode=9)
        assert evaluate(cdp,'document.activeElement.id')=='comentario'
        evaluate(cdp,"document.getElementById('decision-estado').value='APPROVED';document.getElementById('comentario').value='<script>window.approval_xss=1</script>';document.querySelector('.approval-vote').requestSubmit()")
        wait(cdp,"!document.querySelector('.approval-vote') && document.body.textContent.includes('Mi decisión')")
        assert evaluate(cdp,'typeof window.approval_xss')=='undefined'
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        assert not evaluate(cdp,"document.documentElement.outerHTML.includes('"+api.token+"')")
        (tmp_path/f'aprobacion-{width}.png').write_bytes(base64.b64decode(cdp('Page.captureScreenshot',format='png')['data']))
