<?php if (!isset($publicValues, $isPasswordForm)) { http_response_code(404); exit; } ?>
<p class="eyebrow">ACCESO AL SISTEMA</p><h1><?= e($route['title']) ?></h1>
<p class="auth-description"><?= $page === 'solicitar_acceso' ? 'Cuéntanos quién eres y por qué necesitas acceso. El equipo responsable revisará tu solicitud.' : ($isPasswordForm ? 'Elige una contraseña de entre 12 y 1024 caracteres. No compartas tu código de acceso.' : 'Introduce el correo de tu cuenta para solicitar instrucciones.') ?></p>
<?php if ($publicError !== null): ?><div class="notice notice-error" role="alert"><?= e($publicError) ?></div><?php endif; ?>
<?php if ($publicNotice !== null): ?><div class="notice" role="status"><?= e($publicNotice) ?></div>
<?php else: ?>
<form method="post" action="<?= e(page_url($page)) ?>" class="auth-form">
    <input type="hidden" name="csrf_token" value="<?= e($csrfToken) ?>">
    <?php if ($page === 'solicitar_acceso'): ?><div class="form-field"><label for="nombre">Nombre completo</label><input id="nombre" name="nombre" autocomplete="name" minlength="2" maxlength="160" required value="<?= e($publicValues['nombre']) ?>"></div><?php endif; ?>
    <?php if (!$isPasswordForm): ?><div class="form-field"><label for="correo">Correo electrónico</label><input type="email" id="correo" name="correo" autocomplete="email" maxlength="320" required value="<?= e($publicValues['correo']) ?>"></div><?php endif; ?>
    <?php if ($page === 'solicitar_acceso'): ?><div class="form-field"><label for="motivo">Motivo de la solicitud</label><textarea id="motivo" name="motivo" minlength="5" maxlength="2000" required><?= e($publicValues['motivo']) ?></textarea></div><?php endif; ?>
    <?php if ($isPasswordForm): ?>
    <div class="form-field" id="action-token-field"><label for="action-token">Código del correo</label><input type="password" id="action-token" name="token" autocomplete="off" maxlength="256" required><small id="action-token-status">Puedes pegar el código recibido por correo. Si hubo un error, vuelve a pegarlo o abre el enlace nuevamente.</small></div>
    <noscript><p>Para continuar sin JavaScript, usa el enlace alternativo del correo (sin código en la dirección) y pega el código aquí. Se enviará solo al confirmar el formulario.</p></noscript>
    <div class="form-field"><label for="password">Nueva contraseña</label><input type="password" id="password" name="password" autocomplete="new-password" minlength="12" maxlength="1024" required></div>
    <div class="form-field"><label for="confirmation">Repite la contraseña</label><input type="password" id="confirmation" name="confirmation" autocomplete="new-password" minlength="12" maxlength="1024" required></div>
    <?php endif; ?>
    <?php if (!$isPasswordForm) require __DIR__ . '/../includes/turnstile_widget.php'; ?>
    <button class="button button-primary" type="submit"><?= $isPasswordForm ? 'Guardar contraseña' : ($page === 'solicitar_acceso' ? 'Enviar solicitud' : 'Solicitar instrucciones') ?></button>
</form>
<?php endif; ?>
<p class="auth-access"><a href="<?= e(page_url('login')) ?>">Volver a iniciar sesión</a></p>
<?php if ($page === 'restablecer_password'): ?><p class="auth-access"><a href="<?= e(page_url('recuperar_password')) ?>">Solicitar un nuevo enlace</a></p><?php endif; ?>
<?php if ($page === 'establecer_password'): ?><p class="auth-access">Si el enlace venció, contacta al administrador para que reenvíe las instrucciones.</p><?php endif; ?>
