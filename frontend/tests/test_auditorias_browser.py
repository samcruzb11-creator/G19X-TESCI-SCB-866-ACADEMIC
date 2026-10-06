"""Isolated Chrome: real PHP forms, responsive cards and lifecycle controls."""
import base64
import time
import pytest
from test_auth_browser import chromium, evaluate


def wait(cdp, expression):
    deadline=time.monotonic()+10
    while not evaluate(cdp,expression):
        assert time.monotonic()<deadline,'Audit page did not render'
        time.sleep(.05)


def go(cdp,url,expression):
    cdp('Page.navigate',url=url)
    wait(cdp,"document.readyState==='complete' && ("+expression+")")


@pytest.mark.parametrize('width,height',[(1440,1000),(390,844),(320,700)])
def test_audit_list_forms_keyboard_and_cycle(frontend,tmp_path,width,height):
    client,api,_,_=frontend;api.audit['nombre']='Audit with a long but readable business title'
    base=str(client.base_url).rstrip('/')
    with chromium(tmp_path) as cdp:
        cdp('Emulation.setDeviceMetricsOverride',width=width,height=height,deviceScaleFactor=1,mobile=False)
        go(cdp,base+'/index.php?pagina=login',"!!document.getElementById('password')")
        evaluate(cdp,"document.getElementById('correo').value='browser@example.invalid';document.getElementById('password').value='correct';document.querySelector('.auth-form').requestSubmit()")
        wait(cdp,"location.search.includes('pagina=dashboard') && !!document.querySelector('.page-heading')")
        go(cdp,base+'/index.php?pagina=auditorias',"!!document.querySelector('.audit-list')")
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        assert evaluate(cdp,"document.querySelector('.audit-list').textContent.includes('Borrador')")
        evaluate(cdp,"document.querySelector('.audit-more-filters summary').focus()")
        cdp('Input.dispatchKeyEvent',type='keyDown',key='Enter',code='Enter',windowsVirtualKeyCode=13,text='\r',unmodifiedText='\r')
        cdp('Input.dispatchKeyEvent',type='keyUp',key='Enter',code='Enter',windowsVirtualKeyCode=13)
        wait(cdp,"document.querySelector('.audit-more-filters').open")
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        evaluate(cdp,"document.querySelector('.audit-more-filters').open=false")
        if width<760:assert evaluate(cdp,"getComputedStyle(document.querySelector('.audit-list thead')).display")=='none'
        (tmp_path/f'auditorias-{width}.png').write_bytes(base64.b64decode(cdp('Page.captureScreenshot',format='png')['data']))
        go(cdp,base+'/index.php?pagina=auditoria_nueva',"!!document.getElementById('codigo')")
        assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        assert evaluate(cdp,"[...document.querySelectorAll('.form-grid input,.form-grid select,.form-grid textarea')].every(e=>!!document.querySelector('label[for='+e.id+']'))")
        evaluate(cdp,"document.getElementById('codigo').focus()")
        cdp('Input.dispatchKeyEvent',type='keyDown',key='Tab',code='Tab',windowsVirtualKeyCode=9)
        cdp('Input.dispatchKeyEvent',type='keyUp',key='Tab',code='Tab',windowsVirtualKeyCode=9)
        assert evaluate(cdp,'document.activeElement.id')=='nombre'
        evaluate(cdp,"document.getElementById('codigo').value='BROWSER';document.getElementById('nombre').value='Browser audit';document.getElementById('alcance').value='Isolated browser scope';document.getElementById('responsable_id').value='7';document.getElementById('codigo').form.requestSubmit()")
        wait(cdp,"location.search.includes('pagina=auditoria&') && document.body.textContent.includes('Activar auditoría')")
        go(cdp,base+'/index.php?pagina=auditoria_editar&id=1',"!!document.getElementById('nombre')")
        evaluate(cdp,"document.getElementById('nombre').value='Edited in browser';document.getElementById('nombre').form.requestSubmit()")
        wait(cdp,"location.search.includes('pagina=auditoria&') && document.body.textContent.includes('Edited in browser')")
        for target,label in [('IN_PROGRESS','Enviar a revisión'),('IN_REVIEW','Cerrar auditoría'),('COMPLETED','Esta auditoría es terminal')]:
            evaluate(cdp,"document.querySelector('input[name=estado][value="+target+"]').form.requestSubmit()")
            wait(cdp,"document.body.textContent.includes('"+label+"') && !document.querySelector('input[name=estado][value="+target+"]')")
            assert not evaluate(cdp,'document.documentElement.scrollWidth>innerWidth')
        assert not evaluate(cdp,"document.body.textContent.includes('Editar auditoría')")
        assert not evaluate(cdp,"document.documentElement.outerHTML.includes('"+api.token+"')")
        (tmp_path/f'auditoria-cerrada-{width}.png').write_bytes(base64.b64decode(cdp('Page.captureScreenshot',format='png')['data']))
