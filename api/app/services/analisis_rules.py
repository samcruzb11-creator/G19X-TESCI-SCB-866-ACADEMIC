"""Deterministic, bounded local rules; no content reading or external services."""
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import PurePosixPath
import re
import unicodedata
from app.core.config import settings


@dataclass(frozen=True)
class LocalPolicy:
    similarity_threshold: float = 0.92
    candidates_limit: int = 64
    versions_limit: int = 100
    minimum_name_length: int = 8

    def __post_init__(self):
        if not 0.8 <= self.similarity_threshold <= 1:
            raise ValueError('Threshold must be in [0.8, 1]')
        if not 1 <= self.candidates_limit <= 100 or not 1 <= self.versions_limit <= 100:
            raise ValueError('Limits must be in [1, 100]')


POLICY = LocalPolicy(similarity_threshold=settings.analysis_similarity_threshold)


def normalized_name(name):
    """NFKC/casefold, punctuation as spaces; preserve letters, accents and digits."""
    name = unicodedata.normalize('NFKC', name or '').casefold()
    return ' '.join(''.join(' ' if unicodedata.category(c).startswith('P') else c
                           for c in name).split())


def name_parts(name):
    name = unicodedata.normalize('NFKC', name or '').casefold()
    path = PurePosixPath(name.replace('\\', '/'))
    return normalized_name(path.stem), path.suffix


def similarity(left, right, policy=POLICY):
    a, ext_a = name_parts(left)
    b, ext_b = name_parts(right)
    if (not ext_a or ext_a != ext_b or min(len(a), len(b)) < policy.minimum_name_length
            or not set(a.split()) & set(b.split())):
        return None
    # Canonical order removes SequenceMatcher's argument-order asymmetry.
    a, b = sorted((a, b))
    value = SequenceMatcher(None, a, b, autojunk=False).ratio()
    return value if reaches_threshold(value, policy) else None


def reaches_threshold(value, policy=POLICY):
    return value >= policy.similarity_threshold


def valid_hash(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-fA-F]{64}', value) is not None


def storage_status(storage, key):
    """Stat only. Reject links, encoded keys, non-managed paths and traversal."""
    try:
        if not isinstance(key, str) or not key or '%' in key or '\x00' in key:
            return 'RUTA_NO_SEGURA'
        relative = PurePosixPath(key.replace('\\', '/'))
        if relative.parts[0] not in {'documents', 'evidence'} or '..' in relative.parts:
            return 'RUTA_NO_SEGURA'
        # Check lexical components before resolving; never stat a resolved outside target.
        current = storage.base_path
        for part in relative.parts:
            current = current / part
            if current.is_symlink() or current.is_junction():
                return 'RUTA_NO_SEGURA'
        target = storage.get_absolute_path(key)
        return None if target.is_file() else 'ARCHIVO_NO_DISPONIBLE'
    except (ValueError, IndexError):
        return 'RUTA_NO_SEGURA'
    except OSError:
        return 'ARCHIVO_NO_DISPONIBLE'
