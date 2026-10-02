(() => {
    'use strict';
    // Fragment never travels to PHP, reverse proxies or HTTP access logs.
    const actionToken = new URLSearchParams(window.location.hash.slice(1)).get('token');
    if (window.location.hash) history.replaceState(null, '', window.location.pathname + window.location.search);
    const tokenInput = document.getElementById('action-token');
    if (tokenInput && actionToken && /^[A-Za-z0-9_-]{43}$/.test(actionToken)) {
        tokenInput.value = actionToken;
        document.getElementById('action-token-status').textContent = 'Código cargado desde el enlace. Confirma tu nueva contraseña.';
    }
    // Avoid restoring the token from the back/forward page cache.
    window.addEventListener('pagehide', () => { if (tokenInput) tokenInput.value = ''; });
})();
