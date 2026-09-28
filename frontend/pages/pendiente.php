<?php if (!isset($route)) { http_response_code(404); exit; } ?>
<div class="page-heading"><div><p class="eyebrow">ESPACIO DE TRABAJO</p><h1><?= e($route['title']) ?></h1></div></div>
<section class="panel placeholder-panel">
    <?php if ($notFound): ?>
        <h2>No encontramos esta página</h2><p>Comprueba la dirección o vuelve al inicio del sistema.</p>
    <?php else: ?>
        <span class="badge badge-neutral">Próxima fase</span><h2>Esta vista aún no está disponible</h2>
        <p><?php if ($page === 'documento'): ?>La ficha del documento #<?= e($documentId) ?> se habilitará en la siguiente fase.<?php elseif ($page === 'documento_nuevo'): ?>El formulario para registrar documentos se habilitará en la siguiente fase.<?php else: ?>La gestión de <?= e(mb_strtolower($route['title'], 'UTF-8')) ?> se incorporará en una fase posterior.<?php endif; ?></p>
    <?php endif; ?>
    <a class="button button-secondary" href="<?= e(page_url($route['nav'] === 'documentos' ? 'documentos' : 'dashboard')) ?>"><?= $route['nav'] === 'documentos' ? 'Volver a documentos' : 'Volver al dashboard' ?></a>
</section>
