<?php if (!isset($route, $loginEmail)) { http_response_code(404); exit; } ?>
<p class="eyebrow">TU ESPACIO DE TRABAJO</p>
<h1>Todo en orden.<br>Comienza aquí.</h1>
<p class="auth-description">Inicia sesión para consultar y gestionar tus documentos y auditorías.</p>
    <?php if (is_string($loginNotice)): ?><div class="notice" role="status"><?= e($loginNotice) ?></div><?php endif; ?>
    <?php if (is_string($loginError)): ?><div class="notice notice-error" role="alert"><?= e($loginError) ?></div><?php endif; ?>
    <form action="<?= e(page_url('login')) ?>" method="post" class="auth-form" aria-label="Iniciar sesión">
        <input type="hidden" name="csrf_token" value="<?= e($csrfToken) ?>">
        <div class="form-field"><label for="correo">Correo electrónico</label><input type="email" id="correo" name="correo" autocomplete="username" maxlength="320" value="<?= e($loginEmail) ?>" placeholder="nombre@organizacion.com" required></div>
        <div class="form-field"><label for="password">Contraseña</label><input type="password" id="password" name="password" autocomplete="current-password" required></div>
        <p class="auth-recovery">¿Olvidaste tu contraseña? <a href="<?= e(page_url('recuperar_password')) ?>">Restablécela aquí</a></p>
        <?php require __DIR__ . '/../includes/turnstile_widget.php'; ?>
        <button type="submit" class="button button-primary">Iniciar sesión <span aria-hidden="true">→</span></button>
    </form>
<p class="auth-access">¿No tienes una cuenta? <a href="<?= e(page_url('solicitar_acceso')) ?>">Solicita acceso</a></p>
