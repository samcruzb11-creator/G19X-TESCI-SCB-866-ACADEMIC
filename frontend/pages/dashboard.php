<?php if (!isset($route)) { http_response_code(404); exit; } ?>
<div class="page-heading"><div><p class="eyebrow">TRAZABILIDAD Y SEGUIMIENTO</p><h1>Resumen ejecutivo</h1><p class="page-description">Indicadores calculados sobre los recursos autorizados para tu cuenta.</p></div><a class="button button-secondary" href="<?= e(page_url('dashboard')) ?>">Actualizar resumen</a></div>
<?php if (can_show_action('documentos')): ?><section class="panel document-section"><div class="panel-heading"><div><h2>Análisis documental</h2><p>Coincidencias binarias, metadatos y relaciones documentales explicables. Se consulta por separado de las alertas operativas.</p></div><a class="text-link" href="<?= e(page_url('analisis')) ?>">Consultar anomalías documentales</a></div></section><?php endif; ?>
<?php if (!$dashboardResult['ok']): ?>
<div class="notice" role="status"><h2>Información no disponible</h2><p><?= e($dashboardResult['message']) ?></p><p>No se presentan valores mientras el resumen no está disponible.</p></div>
<?php else: ?>
<p class="section-note">Consultado: <?= e(display_date($dashboard['generado_en'] ?? null)) ?>. Alcance según tus permisos actuales.</p>
<section class="metrics dashboard-metrics" aria-label="Totales autorizados">
<?php foreach (['auditorias'=>'Auditorías visibles','hallazgos'=>'Hallazgos visibles','aprobaciones'=>'Rondas visibles','documentos'=>'Documentos visibles','evidencias'=>'Evidencias visibles'] as $key=>$label): $data=$indicatorData[$key] ?? null; if ($data === null) continue; ?>
<div class="metric"><h2><?= e($label) ?></h2><p class="metric-value" data-kpi="<?= e($key) ?>"><?= e($data['total']) ?></p><p class="metric-note">Total dentro de tu alcance</p></div>
<?php endforeach; ?>
<?php if (isset($indicatorData['decisiones']['pendientes_propias'])): ?>
<div class="metric"><h2>Mis decisiones pendientes</h2><p class="metric-value" data-kpi="pendientes_propias"><?= e($indicatorData['decisiones']['pendientes_propias']) ?></p><p class="metric-note">Asignaciones PENDING registradas, incluidas las históricas. La disponibilidad se consulta en cada ronda.</p></div>
<?php endif; ?>
</section>
<section class="panel document-section" aria-labelledby="ratios-title"><div class="panel-heading"><div><h2 id="ratios-title">Indicadores de seguimiento</h2><p>Medidas separadas de avance y cobertura.</p></div></div><div class="dashboard-ratios">
<?php foreach (['auditorias_completadas'=>['Auditorías completadas','Completadas / auditorías no canceladas'], 'hallazgos_cerrados'=>['Hallazgos cerrados','Cerrados / todos los hallazgos; riesgo aceptado se conserva separado'], 'rondas_resueltas'=>['Rondas con decisión final','Aprobadas, rechazadas o con cambios solicitados / rondas no canceladas'], 'documentos_con_version'=>['Documentos con versión','Con al menos una versión / documentos visibles']] as $key=>[$label,$formula]): $ratio=$indicatorData[$key]; if ($ratio['estado']==='NOT_APPLICABLE') continue; ?>
<div class="dashboard-ratio"><h3><?= e($label) ?></h3><p class="metric-value"><?= $ratio['porcentaje'] === null ? 'Sin datos' : e(number_format((float)$ratio['porcentaje'], 2, ',', '.')) . '%' ?></p><p><?= e($ratio['numerador']) ?> / <?= e($ratio['denominador']) ?></p><p class="metric-note"><?= e($formula) ?></p></div>
<?php endforeach; ?>
<?php if (($indicatorData['documentos_con_version']['estado'] ?? '')==='NOT_APPLICABLE'): ?><p class="section-note">Cobertura documental no disponible para tu alcance de versiones.</p><?php endif; ?>
</div></section>
<div class="dashboard-grid">
<?php foreach (['auditorias'=>['Auditorías por estado','auditorias'],'hallazgos'=>['Hallazgos por estado','hallazgos'],'aprobaciones'=>['Rondas por estado','aprobaciones'],'decisiones'=>['Decisiones de rondas visibles','aprobaciones'],'evidencias'=>['Evidencias por tipo','evidencias']] as $key=>[$label,$module]): $data=$indicatorData[$key] ?? null; if ($data===null) continue; ?>
<section class="panel" aria-labelledby="states-<?= e($key) ?>"><div class="panel-heading"><h2 id="states-<?= e($key) ?>"><?= e($label) ?></h2><a class="text-link" href="<?= e(page_url($module)) ?>">Consultar <?= e(strtolower($module)) ?></a></div><dl class="dashboard-distribution">
<?php foreach ($data['por_estado'] as $state=>$count): if ($state==='DESCONOCIDO' && $count===0) continue; ?><div><dt><?= e(dashboard_state_label($state)) ?></dt><dd><?= e($count) ?></dd></div><?php endforeach; ?>
</dl><?php if ($key==='decisiones'): ?><p class="section-note">Resueltas: <?= e($data['resueltas']) ?>. Las pendientes pueden pertenecer a rondas históricas.</p><?php endif; ?></section>
<?php endforeach; ?>
<?php if (isset($indicatorData['documentos'])): ?><section class="panel" aria-labelledby="versions-title"><div class="panel-heading"><h2 id="versions-title">Versiones documentales</h2><a class="text-link" href="<?= e(page_url('documentos')) ?>">Consultar documentos</a></div><dl class="dashboard-distribution"><div><dt>Versiones visibles</dt><dd><?= e($indicatorData['documentos']['versiones']) ?></dd></div><?php if (isset($indicatorData['documentos']['sin_version'])): ?><div><dt>Documentos sin versión</dt><dd><?= e($indicatorData['documentos']['sin_version']) ?></dd></div><?php endif; ?></dl></section><?php endif; ?>
</div>
<section class="panel document-section dashboard-alerts" aria-labelledby="alerts-title"><div class="panel-heading"><div><h2 id="alerts-title">Alertas prioritarias</h2><p><?= e($alertData['total']) ?> alertas derivadas dentro de tu alcance.</p></div><a class="text-link" href="<?= e(page_url('alertas')) ?>">Consultar todas las alertas</a></div><?php require __DIR__.'/../includes/dashboard_alert_list.php'; ?></section>
<section class="panel document-section" aria-labelledby="activity-title"><div class="panel-heading"><div><h2 id="activity-title">Actividad reciente autorizada</h2><p>Hasta cinco eventos permitidos por tu acceso al historial.</p></div></div>
<?php if ($activityData['items']===[]): ?><div class="empty-state"><h3>No hay actividad disponible en tu alcance de historial.</h3></div><?php else: ?><ul class="dashboard-items"><?php foreach ($activityData['items'] as $item): $url=dashboard_destination($item['destino']); ?><li><div><h3><?= e($item['titulo']) ?></h3><p><?= e(display_date($item['ocurrido_en'])) ?></p></div><?php if ($url!==null): ?><a class="text-link" href="<?= e($url) ?>">Consultar recurso #<?= e($item['destino']['id']) ?></a><?php endif; ?></li><?php endforeach; ?></ul><?php endif; ?>
</section>
<p class="context-note">Las alertas se calculan al consultar. INFO describe un estado; WARNING señala un hallazgo sin resolver o un documento activo/borrador sin versión. El detalle del recurso confirma las acciones disponibles. No existe un score global de cumplimiento ni un catálogo de documentos requeridos.</p>
<?php endif; ?>
<nav class="module-links" aria-label="Accesos a los módulos"><?php foreach (navigation_items() as $key=>$label): if ($key==='dashboard') continue; ?><a class="text-link" href="<?= e(page_url($key)) ?>"><?= e($label) ?></a><?php endforeach; ?></nav>
