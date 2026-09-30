<?php
declare(strict_types=1);

/** Filters operate on API results only; no direct data access. */
function list_query(string $key, int $max = 200): string
{
    $raw = $_GET[$key] ?? '';
    return is_string($raw) && mb_check_encoding($raw, 'UTF-8') ? mb_substr(trim($raw), 0, $max, 'UTF-8') : '';
}

function list_matches(array $row, string $query, array $fields): bool
{
    if ($query === '') return true;
    foreach ($fields as $field) {
        if (is_string($row[$field] ?? null) && mb_stripos($row[$field], $query, 0, 'UTF-8') !== false) return true;
    }
    return false;
}

function list_filters(string $page, array $values, array $selects, ?string $searchLabel = null): void
{
    ?>
    <form action="index.php" method="get" class="list-filters" role="search" aria-label="Filtrar listado">
        <input type="hidden" name="pagina" value="<?= e($page) ?>">
        <?php if ($searchLabel !== null): ?>
        <div class="form-field filter-search"><label for="filter-q"><?= e($searchLabel) ?></label><input type="search" id="filter-q" name="q" maxlength="200" value="<?= e($values['q'] ?? '') ?>"></div>
        <?php endif; ?>
        <?php foreach ($selects as $name => $config): ?>
        <div class="form-field"><label for="filter-<?= e($name) ?>"><?= e($config['label']) ?></label><select id="filter-<?= e($name) ?>" name="<?= e($name) ?>">
            <option value=""><?= e($config['all']) ?></option>
            <?php foreach ($config['options'] as $value => $label): ?><option value="<?= e($value) ?>"<?= (string) ($values[$name] ?? '') === (string) $value ? ' selected' : '' ?>><?= e($label) ?></option><?php endforeach; ?>
        </select></div>
        <?php endforeach; ?>
        <div class="filter-actions"><button type="submit" class="button button-secondary">Aplicar filtros</button><a class="text-link" href="<?= e(page_url($page)) ?>">Limpiar</a></div>
    </form>
    <?php
}
