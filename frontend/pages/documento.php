<?php if (!isset($documentResult, $route)) { http_response_code(404); exit; } ?>
<?php if (!$documentResult['ok']): ?>
    <div class="page-heading"><h1>Documento</h1><a class="button button-secondary" href="<?= e(page_url('documentos')) ?>">Volver a documentos</a></div>
    <section class="panel empty-state" role="status"><h2><?= $documentResult['status'] === 404 ? 'El documento solicitado no está disponible.' : 'No fue posible consultar el documento.' ?></h2><p>Vuelve al listado o intenta la consulta nuevamente.</p></section>
<?php return; endif; ?>
<?php
[$statusLabel, $statusClass] = document_status($document['estado'] ?? null);
$currentVersionId = positive_id($document['version_vigente_id'] ?? null);
?>
<div class="page-heading document-heading">
    <div><p class="eyebrow"><?= e($document['codigo'] ?? '') ?></p><h1><?= e($document['titulo'] ?? 'Documento') ?></h1><div class="document-tags"><span class="badge badge-<?= e($statusClass) ?>"><?= e($statusLabel) ?></span><?php if (is_string($document['tipo'] ?? null)): ?><span class="document-type"><?= e($document['tipo']) ?></span><?php endif; ?></div></div>
    <a class="button button-secondary" href="<?= e(page_url('documentos')) ?>">Volver a documentos</a>
</div>
<?php if (is_string($successMessage)): ?><div class="notice notice-success" role="status"><?= e($successMessage) ?></div><?php endif; ?>
<?php if ($downloadError !== null): ?><div class="notice notice-error" role="alert"><?= e($downloadError) ?></div><?php endif; ?>
<div class="document-actions"><?php if (can_show_action('version_cargar')): ?><a class="button button-primary" href="#nueva-version">Subir nueva versión</a><?php endif; ?><?php if ($currentVersionId !== null): ?><a class="button button-secondary" href="<?= e(download_url($documentId, $currentVersionId)) ?>">Descargar versión vigente</a><?php endif; ?></div>

<section class="panel document-section" aria-labelledby="general-title">
    <div class="panel-heading"><h2 id="general-title">Información general</h2><span class="record-count"><?= e($currentVersionId === null ? (user_has_role('APROBADOR') ? 'No disponible' : 'Sin versión vigente') : version_label($document) . ' vigente') ?></span></div>
    <?php if (!$areaResult['ok'] || !$userResult['ok']): ?><p class="section-note">No fue posible consultar todos los nombres. Se muestran los identificadores disponibles.</p><?php endif; ?>
    <dl class="document-info">
        <div class="info-wide"><dt>Descripción</dt><dd class="preserve-lines"><?= e($document['descripcion'] ?? 'Sin descripción registrada.') ?></dd></div>
        <div><dt>Área</dt><dd><?= e(area_name($document, $areaNames)) ?></dd></div>
        <div><dt>Responsable</dt><dd><?= e(user_name($document['responsable_id'] ?? null, $userNames)) ?></dd></div>
        <div><dt>Creado por</dt><dd><?= e(user_name($document['created_by_id'] ?? null, $userNames)) ?></dd></div>
        <div><dt>Versión vigente</dt><dd><?= e(version_label($document)) ?></dd></div>
        <div><dt>Fecha de creación</dt><dd><?= e(display_date($document['created_at'] ?? null)) ?></dd></div>
        <div><dt>Última actualización</dt><dd><?= e(display_date($document['updated_at'] ?? null)) ?></dd></div>
    </dl>
</section>

<section class="panel document-section" aria-labelledby="versions-title">
    <div class="panel-heading"><div><h2 id="versions-title"><?= user_has_role('APROBADOR') ? 'Versiones asignadas' : 'Historial de versiones' ?></h2><p>Archivos registrados y su huella de integridad.</p></div><?php if ($versionResult['ok']): ?><span class="record-count"><?= e(count($versions)) ?> <?= count($versions) === 1 ? 'versión' : 'versiones' ?></span><?php endif; ?></div>
    <?php if (!$versionResult['ok']): ?><div class="empty-state" role="status"><p>No fue posible consultar las versiones.</p></div>
    <?php elseif ($versions === []): ?><div class="empty-state"><p><?= user_has_role('APROBADOR') ? 'No hay versiones disponibles.' : 'Este documento aún no tiene versiones.' ?></p></div>
    <?php else: ?>
    <div class="table-scroll" role="region" aria-label="Historial de versiones" tabindex="0"><table class="data-table versions-table"><thead><tr><th scope="col">Versión</th><th scope="col">Archivo</th><th scope="col">SHA-256</th><th scope="col">Tamaño</th><th scope="col">Fecha</th><th scope="col">Usuario</th><th scope="col" class="action-cell">Acción</th></tr></thead><tbody>
    <?php foreach ($versions as $version): $versionId = positive_id($version['id'] ?? null); $hash = is_string($version['sha256'] ?? null) ? $version['sha256'] : ''; ?>
        <tr><td class="version-cell">v<?= e($version['numero_version'] ?? '—') ?><?php if ($versionId === $currentVersionId): ?><span class="badge badge-success version-current">Vigente</span><?php endif; ?></td>
            <td class="file-cell"><?= e($version['nombre_original'] ?? 'Archivo') ?><?php if (is_string($version['comentario_cambio'] ?? null) && $version['comentario_cambio'] !== ''): ?><small><?= e($version['comentario_cambio']) ?></small><?php endif; ?></td>
            <td><details class="hash-details"><summary title="<?= e($hash) ?>"><?= e($hash !== '' ? substr($hash, 0, 12) . '…' : '—') ?></summary><code><?= e($hash) ?></code></details></td>
            <td class="version-cell"><?= e(file_size_label($version['tamano_bytes'] ?? null)) ?></td><td class="date-cell"><?= e(display_date($version['created_at'] ?? null)) ?></td><td><?= e(user_name($version['subido_por_id'] ?? null, $userNames)) ?></td>
            <td class="action-cell"><?php if ($versionId !== null): ?><a class="table-link" href="<?= e(download_url($documentId, $versionId)) ?>">Descargar</a><?php else: ?>—<?php endif; ?></td>
        </tr>
    <?php endforeach; ?>
    </tbody></table></div><?php endif; ?>
</section>

<?php if (can_show_action('historial')): ?>
<section class="panel document-section" aria-labelledby="history-title">
    <div class="panel-heading"><div><h2 id="history-title">Historial de trazabilidad</h2><p>Eventos del documento en orden cronológico.</p></div></div>
    <?php if (!$historyResult['ok']): ?><div class="empty-state" role="status"><p>No fue posible consultar el historial.</p></div>
    <?php elseif ($historyResult['data'] === []): ?><div class="empty-state"><p>No hay eventos registrados.</p></div>
    <?php else: ?>
    <div class="table-scroll" role="region" aria-label="Historial de trazabilidad" tabindex="0"><table class="data-table history-table"><thead><tr><th scope="col">Fecha / hora</th><th scope="col">Acción</th><th scope="col">Usuario / actor</th><th scope="col">Detalle</th></tr></thead><tbody>
    <?php foreach ($historyResult['data'] as $event): ?>
        <tr><td class="date-cell"><?= e(display_date($event['ocurrido_en'] ?? null)) ?></td><td><?= e(event_label($event['accion'] ?? null)) ?></td><td class="actor-cell"><?= e(is_string($event['actor_snapshot'] ?? null) && $event['actor_snapshot'] !== '' ? $event['actor_snapshot'] : user_name($event['actor_id'] ?? null, $userNames)) ?></td><td><ul class="event-details"><?php foreach (event_details($event) as $detail): ?><li><?= e($detail) ?></li><?php endforeach; ?></ul></td></tr>
    <?php endforeach; ?>
    </tbody></table></div><?php endif; ?>
</section>

<?php endif; ?>
<?php if (can_show_action('version_cargar')): ?>
<section class="panel document-section" id="nueva-version" aria-labelledby="upload-title">
    <div class="panel-heading"><div><h2 id="upload-title">Subir nueva versión</h2><p>Selecciona el archivo para registrar una nueva versión. Los campos con * son obligatorios.</p></div></div>
    <div class="upload-body">
        <?php if ($uploadError !== null): ?><div class="notice notice-error" role="alert"><?= e($uploadError) ?></div><?php endif; ?>

        <form action="<?= e(page_url('documento', ['id' => $documentId])) ?>#nueva-version" method="post" enctype="multipart/form-data" class="upload-form">
            <input type="hidden" name="csrf_token" value="<?= e($csrfToken) ?>">
            <div class="form-grid">
                <?php
                $uploadValues = ['comentario_cambio' => $comment];
                form_control('archivo', 'Archivo', $uploadValues, $uploadFieldErrors, 'file', true);
                form_control('comentario_cambio', 'Motivo o comentario', $uploadValues, $uploadFieldErrors, 'textarea');
                ?>
            </div>
            <p class="field-help">Límite por archivo: <?= e(ini_get('upload_max_filesize')) ?>. Límite del envío completo: <?= e(ini_get('post_max_size')) ?>.</p><div class="form-actions"><button type="submit" class="button button-primary"<?= !$sessionReady ? ' disabled' : '' ?>>Cargar versión</button><a class="button button-secondary" href="<?= e(page_url('documento', ['id' => $documentId])) ?>">Cancelar</a><span class="field-help">La carga quedará registrada en el historial de trazabilidad.</span></div>
        </form>
    </div>
</section>

<?php endif; ?>
