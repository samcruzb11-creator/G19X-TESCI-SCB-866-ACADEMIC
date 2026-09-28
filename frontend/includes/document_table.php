<?php if (!isset($documents, $areaNames)) { http_response_code(404); exit; } ?>
<div class="table-scroll" role="region" aria-label="Documentos registrados" tabindex="0">
    <table class="data-table">
        <caption class="sr-only">Documentos: código, título, área, estado, versión vigente y actualización</caption>
        <thead><tr><th scope="col">Código</th><th scope="col">Título</th><th scope="col">Área</th><th scope="col">Estado</th><th scope="col">Versión vigente</th><th scope="col">Actualización</th><th scope="col" class="action-cell">Acciones</th></tr></thead>
        <tbody>
        <?php foreach ($documents as $document): ?>
            <?php [$statusLabel, $statusClass] = document_status($document['estado'] ?? null); $id = positive_id($document['id'] ?? null); ?>
            <tr>
                <td class="document-code"><?= e($document['codigo'] ?? '—') ?></td>
                <td class="document-title"><?= e($document['titulo'] ?? 'Sin título') ?></td>
                <td class="area-cell"><?= e(area_name($document, $areaNames)) ?></td>
                <td><span class="badge badge-<?= e($statusClass) ?>"><?= e($statusLabel) ?></span></td>
                <td class="version-cell"><?= e(version_label($document)) ?></td>
                <td class="date-cell"><?= e(display_date($document['updated_at'] ?? null)) ?></td>
                <td class="action-cell"><?php if ($id !== null): ?><a class="table-link" href="<?= e(page_url('documento', ['id' => $id])) ?>">Ver detalle<span class="sr-only"> de <?= e($document['codigo'] ?? '') ?></span></a><?php else: ?>—<?php endif; ?></td>
            </tr>
        <?php endforeach; ?>
        </tbody>
    </table>
</div>
