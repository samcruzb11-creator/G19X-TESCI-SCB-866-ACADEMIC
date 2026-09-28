<?php if (!isset($route)) { http_response_code(404); exit; } ?>
<aside class="sidebar" id="sidebar">
    <a class="brand" href="<?= e(page_url('dashboard')) ?>" aria-label="Sistema de Trazabilidad, inicio">
        <span class="brand-mark" aria-hidden="true">ST</span>
        <span><strong>Trazabilidad</strong><small>Gestión documental</small></span>
    </a>
    <div class="nav-label">ESPACIO DE TRABAJO</div>
    <nav aria-label="Navegación principal">
        <?php foreach (['dashboard' => 'Dashboard', 'documentos' => 'Documentos', 'auditorias' => 'Auditorías', 'evidencias' => 'Evidencias'] as $key => $label): ?>
            <a class="nav-link<?= $route['nav'] === $key ? ' is-active' : '' ?>" href="<?= e(page_url($key)) ?>"<?= $route['nav'] === $key ? ' aria-current="page"' : '' ?>><?= e($label) ?></a>
        <?php endforeach; ?>
    </nav>
    <div class="sidebar-footer"><span><?= e(APP_NAME) ?></span><small>Versión MVP · Entorno local</small></div>
</aside>
