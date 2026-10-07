<?php if (!isset($route)) { http_response_code(404); exit; } ?>
<?php if ($alertData['items']===[]): ?><div class="empty-state"><h3>No hay alertas para esta consulta.</h3></div><?php else: ?>
<ul class="dashboard-items">
<?php foreach ($alertData['items'] as $alert): $url=dashboard_destination($alert['destino']); ?>
<li><div><p><span class="badge <?= $alert['severidad']==='WARNING' ? 'badge-warning' : 'badge-neutral' ?>"><?= e($alert['severidad']==='WARNING' ? 'WARNING · Atención' : 'INFO · Información') ?></span></p><h3><?= e($alert['titulo']) ?></h3><p class="dashboard-resource-name"><?= e($alert['nombre']) ?></p><p><?= e($alert['descripcion']) ?></p><p class="metric-note">Última actualización: <?= e(display_date($alert['fecha'])) ?></p></div><?php if ($url!==null): ?><a class="text-link" href="<?= e($url) ?>">Consultar <?= e(['auditoria'=>'auditoría','hallazgo'=>'hallazgo','documento'=>'documento','aprobacion'=>'ronda'][$alert['recurso']] ?? 'recurso') ?> #<?= e($alert['recurso_id']) ?></a><?php endif; ?></li>
<?php endforeach; ?>
</ul><?php endif; ?>
