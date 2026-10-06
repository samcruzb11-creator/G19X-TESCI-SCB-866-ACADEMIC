(() => {
    'use strict';
    const panel = document.querySelector('[data-turnstile]');
    if (!panel) return;
    const form = panel.closest('form');
    const input = panel.querySelector('input[name="turnstile_token"]');
    const status = document.getElementById('verification-status');
    const container = document.getElementById('turnstile-widget');
    const retry = panel.querySelector('.verification-retry');
    const submit = form.querySelector('button[type="submit"]');
    const api = document.getElementById('turnstile-api');
    let widget = null;
    let pendingToken = '';
    let lifetime = null;
    let submitted = false;
    let renderedSize = null;

    function clear(message, retryable = true) {
        input.value = '';
        pendingToken = '';
        window.clearTimeout(lifetime);
        status.textContent = message;
        retry.hidden = !retryable;
    }
    function expired() {
        clear('La verificación venció. Reiníciala para continuar.');
    }
    function render() {
        if (!window.turnstile || widget !== null) return;
        // Flexible requires 300 px. Reserve 20 px for a scrollbar appearing on render.
        renderedSize = container.clientWidth < 320 ? 'compact' : 'flexible';
        try {
            widget = window.turnstile.render(container, {
                sitekey: panel.dataset.sitekey, action: panel.dataset.action,
                theme: 'light', language: 'es', size: renderedSize, tabindex: 0,
                'response-field': false, retry: 'never',
                'refresh-expired': 'manual', 'refresh-timeout': 'manual',
                callback: token => {
                    if (typeof token !== 'string' || token.length === 0 || token.length > 2048) {
                        clear('No se pudo completar la verificación. Reiníciala.');
                        return;
                    }
                    // A hidden input's value property reflects into its HTML attribute.
                    // Keep the credential in this closure until the outgoing FormData.
                    pendingToken = token;
                    status.textContent = 'Verificación completada. Puedes continuar.';
                    retry.hidden = true;
                    window.clearTimeout(lifetime);
                    lifetime = window.setTimeout(expired, 300000);
                },
                'expired-callback': expired,
                'timeout-callback': () => clear('La verificación agotó su tiempo. Reiníciala para continuar.'),
                'error-callback': () => {
                    clear('No se pudo completar la verificación. Reiníciala o intenta más tarde.');
                    return true;
                },
            });
        } catch (_) {
            clear('No podemos cargar la verificación. Intenta más tarde.', false);
        }
    }
    retry.addEventListener('click', () => {
        if (!window.turnstile || widget === null) return;
        clear('Preparando una nueva verificación…', false);
        try { window.turnstile.reset(widget); }
        catch (_) { clear('No podemos cargar la verificación. Intenta más tarde.', false); }
    });
    form.addEventListener('submit', event => {
        if (!pendingToken || submitted) {
            event.preventDefault();
            if (!submitted) {
                status.textContent = 'Completa la verificación para continuar.';
                status.focus();
            }
            return;
        }
        submitted = true;
        submit.disabled = true;
    });
    // Insert exactly once in the outgoing body, never in HTML/storage/URL.
    form.addEventListener('formdata', event => {
        event.formData.set('turnstile_token', pendingToken);
        pendingToken = '';
        input.value = '';
        const password = form.querySelector('input[type="password"]');
        if (password) password.value = '';
    });
    window.addEventListener('pagehide', () => {
        clear('Completa una nueva verificación para continuar.', false);
        const password = form.querySelector('input[type="password"]');
        if (password) password.value = '';
        if (window.turnstile && widget !== null) window.turnstile.remove(widget);
        widget = null;
    });
    window.addEventListener('pageshow', event => {
        if (event.persisted) {
            submitted = false;
            submit.disabled = false;
            render();
        }
    });
    window.addEventListener('resize', () => {
        const size = container.clientWidth < 320 ? 'compact' : 'flexible';
        if (window.turnstile && widget !== null && size !== renderedSize && !submitted) {
            clear('Preparando una nueva verificación…', false);
            window.turnstile.remove(widget);
            widget = null;
            render();
        }
    });
    api.addEventListener('load', () => { if (window.turnstile) window.turnstile.ready(render); });
    api.addEventListener('error', () => clear('No podemos cargar la verificación. Intenta más tarde.', false));
    if (window.turnstile) window.turnstile.ready(render);
})();
