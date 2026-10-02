<?php if (!isset($route)) { http_response_code(404); exit; } ?>
<!doctype html>
<html lang="es"><head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light">
    <title><?= e($route['title']) ?> · Sistema de Trazabilidad</title>
    <link rel="stylesheet" href="assets/css/estilos.css">
    <link rel="stylesheet" href="assets/css/auth.css">
    <?php if (in_array($page, ['restablecer_password','establecer_password'], true)): ?><script src="assets/js/password_reset.js" defer></script><?php endif; ?>
</head><body class="auth-page">
<a class="skip-link" href="#contenido">Ir al contenido</a>
<header class="auth-brand"><a href="<?= e(page_url('login')) ?>"><span class="auth-mark" aria-hidden="true">ST</span><span>Sistema de Trazabilidad<small>GESTIÓN DOCUMENTAL Y AUDITORÍAS</small></span></a></header>
<div class="auth-layout"><main id="contenido" class="auth-form-column" tabindex="-1"><div class="auth-form-inner">
