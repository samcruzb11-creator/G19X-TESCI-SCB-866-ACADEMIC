'use strict';

const menuButton = document.querySelector('.menu-toggle');
if (menuButton) {
    const closeMenu = () => {
        document.body.classList.remove('navigation-open');
        menuButton.setAttribute('aria-expanded', 'false');
    };
    menuButton.addEventListener('click', () => {
        const open = document.body.classList.toggle('navigation-open');
        menuButton.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && document.body.classList.contains('navigation-open')) {
            closeMenu();
            menuButton.focus();
        }
    });
    document.addEventListener('click', (event) => {
        if (!event.target.closest('.sidebar, .menu-toggle')) closeMenu();
    });
    window.matchMedia('(min-width: 761px)').addEventListener('change', closeMenu);
}

// Server validation retains values and identifies the first field to correct.
const invalidField = document.querySelector('[aria-invalid="true"]');
if (invalidField) invalidField.focus();

// Only the dependent version selector needs JavaScript; PHP still validates it.
const evidenceForm = document.querySelector('[data-evidence-form]');
if (evidenceForm) {
    const documentSelect = evidenceForm.querySelector('[name="documento_id"]');
    const versionSelect = evidenceForm.querySelector('[name="version_documento_id"]');
    const status = document.querySelector('#version-status');
    let request = null;
    let sequence = 0;
    versionSelect.disabled = !documentSelect.value;
    documentSelect.addEventListener('change', async () => {
        if (request) request.abort();
        const current = ++sequence;
        versionSelect.replaceChildren(new Option('Sin vincular', ''));
        versionSelect.disabled = true;
        status.textContent = '';
        if (!documentSelect.value) return;
        request = new AbortController();
        const controller = request;
        const timer = setTimeout(() => controller.abort(), 12000);
        status.textContent = 'Consultando versiones…';
        const url = new URL('index.php', window.location.href);
        url.searchParams.set('pagina', 'versiones_documento');
        url.searchParams.set('id', documentSelect.value);
        try {
            const response = await fetch(url, {signal: controller.signal, headers: {Accept: 'application/json'}});
            if (response.status === 401) {
                const login = new URL('index.php', window.location.href);
                login.searchParams.set('pagina', 'login');
                window.location.assign(login);
                return;
            }
            if (!response.ok) throw new Error('Unavailable');
            const versions = await response.json();
            if (!Array.isArray(versions)) throw new Error('Invalid response');
            if (current !== sequence) return;
            versions.forEach(version => {
                if (Number.isSafeInteger(version.id) && version.id > 0 && Number.isSafeInteger(version.numero_version)) {
                    versionSelect.add(new Option('v' + version.numero_version, String(version.id)));
                }
            });
            versionSelect.disabled = versions.length === 0;
            status.textContent = versions.length ? 'Selecciona una versión si deseas vincularla.' : 'El documento aún no tiene versiones.';
        } catch {
            if (current === sequence) status.textContent = 'No fue posible consultar las versiones. Selecciona nuevamente el documento o déjalo sin vincular.';
        } finally {
            clearTimeout(timer);
        }
    });
    evidenceForm.querySelector('[name="auditoria_id"]').addEventListener('change', () => {
        if (request) request.abort();
        sequence++;
        documentSelect.value = '';
        versionSelect.replaceChildren(new Option('Sin vincular', ''));
        versionSelect.disabled = true;
        status.textContent = '';
    });
    const type = evidenceForm.querySelector('[name="tipo"]');
    const reference = evidenceForm.querySelector('[name="referencia_url"]');
    if (type && reference) {
        const updateRequirement = () => { reference.required = type.value === 'REFERENCE'; };
        type.addEventListener('change', updateRequirement);
        updateRequirement();
    }
}
