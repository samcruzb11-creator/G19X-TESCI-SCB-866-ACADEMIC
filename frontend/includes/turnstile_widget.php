<?php if (!isset($turnstileWidget) || $turnstileWidget === null) return; ?>
<div class="auth-verification" data-turnstile data-sitekey="<?= e($turnstileWidget['site_key']) ?>" data-action="<?= e($turnstileWidget['action']) ?>">
    <p id="verification-label">Completa la verificación para continuar.</p>
    <div id="turnstile-widget" aria-labelledby="verification-label"></div>
    <input type="hidden" name="turnstile_token" value="" autocomplete="off">
    <p id="verification-status" role="status" aria-live="polite" tabindex="-1">Preparando la verificación…</p>
    <button class="button verification-retry" type="button" hidden>Reiniciar verificación</button>
    <noscript><p>La verificación requiere JavaScript. Actívalo y vuelve a enviar el formulario para continuar.</p></noscript>
</div>
