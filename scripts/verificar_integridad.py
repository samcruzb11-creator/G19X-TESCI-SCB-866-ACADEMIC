"""Read-only checker. Exit 0: clean; 1: discrepancies; 2: incomplete/error."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.storage_integrity import read_references, scan_storage


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Verifica BD/storage sin borrar, mover ni reparar.")
    parser.add_argument("--database-url-env", help="Variable con URL alternativa; p. ej. TEST_DATABASE_URL. No acepta credenciales en argumentos.")
    parser.add_argument("--storage-root", type=Path)
    parser.add_argument("--temporary-age", type=int, default=3600, help="Edad en segundos para marcar temporal posiblemente abandonado.")
    args = parser.parse_args(argv)
    if args.database_url_env and args.storage_root is None:
        parser.error("Una base alternativa requiere --storage-root explicito; no se permite usar el storage real por defecto.")
    if args.storage_root is None:
        args.storage_root = settings.storage_path
    if args.temporary_age < 0:
        parser.error("La edad del temporal no puede ser negativa.")
    engine = None
    try:
        url = os.environ[args.database_url_env] if args.database_url_env else settings.database_url
        engine = create_engine(url, pool_pre_ping=True)
        with Session(engine, autoflush=False) as db:
            references = read_references(db)
        report = scan_storage(references, args.storage_root, args.temporary_age)
        print("Verificación de solo lectura. Pausa las cargas para confirmar candidatos a huérfano.")
        print(f"Registros examinados: {report.checked}; incidencias: {len(report.issues)}")
        for kind, count in sorted(report.counts.items()):
            print(f"  {kind}: {count}")
        for issue in report.issues:
            print(json.dumps(issue, ensure_ascii=True))
        return report.exit_code
    except Exception:
        print("No fue posible completar la verificación. Comprueba conexión y acceso al storage; no se modificó ningún dato.", file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
