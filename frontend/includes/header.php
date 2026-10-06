<?php if (!isset($route)) { http_response_code(404); exit; } ?>
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light">
    <title><?= e($route['title']) ?> · <?= e(APP_NAME) ?></title>
    <link rel="stylesheet" href="assets/css/estilos.css">
    <script src="assets/js/app.js" defer></script>
</head>
<body>
<a class="skip-link" href="#contenido">Ir al contenido</a>
<?php if (current_user() !== null) require __DIR__ . '/sidebar.php'; ?>
<div class="workspace<?= current_user() === null ? ' workspace-public' : '' ?>">
    <header class="topbar">
        <div class="topbar-location">
            <?php if (current_user() !== null): ?>
            <button class="menu-toggle" type="button" aria-controls="sidebar" aria-expanded="false">Menú</button>
            <?php $parentPage = in_array($route['nav'], ['aprobaciones', 'documentos', 'auditorias', 'evidencias'], true) && $page !== $route['nav'] ? $route['nav'] : 'dashboard'; ?>
            <a class="breadcrumb-parent" href="<?= e(page_url($parentPage)) ?>"><?= e(['aprobaciones'=>'Aprobaciones', 'documentos' => 'Documentos', 'auditorias' => 'Auditorías', 'evidencias' => 'Evidencias', 'dashboard' => 'Inicio'][$parentPage]) ?></a><span class="breadcrumb-divider" aria-hidden="true">/</span>
            <span class="header-title"><?= e($route['title']) ?></span>
            <?php else: ?><span class="header-title"><?= e(APP_NAME) ?></span><?php endif; ?>
        </div>
        <?php if (current_user() !== null): ?>
        <div class="account-actions"><span class="current-user"><?= e(current_user()['nombre']) ?> · <?= e(current_user()['rol']) ?></span>
        <form action="<?= e(page_url('logout')) ?>" method="post"><input type="hidden" name="csrf_token" value="<?= e($csrfToken) ?>"><button class="button button-secondary" type="submit">Cerrar sesión</button></form></div>
        <?php endif; ?>
    </header>
    <main id="contenido" class="content" tabindex="-1">
