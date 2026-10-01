<?php if (!isset($route, $errorMessage)) { http_response_code(404); exit; } ?>
<section class="panel placeholder-panel" role="alert"><h1><?= e($route['title']) ?></h1><p><?= e($errorMessage) ?></p>
<a class="button button-secondary" href="<?= e(page_url(current_user() === null ? 'login' : 'dashboard')) ?>">Volver al inicio</a></section>
