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
<?php require __DIR__ . '/sidebar.php'; ?>
<div class="workspace">
    <header class="topbar">
        <div class="topbar-location">
            <button class="menu-toggle" type="button" aria-controls="sidebar" aria-expanded="false">Menú</button>
            <span class="breadcrumb-parent">Espacio de trabajo</span><span class="breadcrumb-divider" aria-hidden="true">/</span>
            <span class="header-title"><?= e($route['title']) ?></span>
        </div>
        <span class="current-user">Usuario del sistema</span>
    </header>
    <main id="contenido" class="content" tabindex="-1">
