"""Run bounded local mail work. No secrets/recipients in command output."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
from app.services.auth_mail import process_one, validate_mail_config


def main(argv=None):
    parser = argparse.ArgumentParser(description='Procesa correo de autenticación pendiente')
    parser.add_argument('--max-jobs', type=int, default=20)
    args = parser.parse_args(argv)
    if not 1 <= args.max_jobs <= 100:
        parser.error('max-jobs debe estar entre 1 y 100')
    try:
        validate_mail_config()
        from app.db.session import SessionLocal
        total = 0
        for _ in range(args.max_jobs):
            if not process_one(SessionLocal):
                break
            total += 1
        print(f'Trabajos procesados: {total}')
        return 0
    except Exception:
        print('No se completó el procesamiento. Revise configuración y conectividad.')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
