"""Bounded MySQL maintenance. Never reports session IDs or login identifiers."""
import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import text


def prune(db, kind, *, dry_run=False, batch_size=500, max_batches=20, now=None):
    if not 1 <= batch_size <= 5000 or not 1 <= max_batches <= 1000:
        raise ValueError("Invalid maintenance limits")
    table, key = {"sessions": ("auth_sessions", "sid"),
                  "limits": ("auth_login_limits", "identifier")}[kind]
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(hours=24) if kind == "sessions" else now
    parameters = {"cutoff": cutoff, "batch": batch_size}
    try:
        if dry_run:
            # Count at most this run's capacity, without fetching identifiers.
            count = db.scalar(text(f"SELECT COUNT(*) FROM (SELECT 1 FROM {table} "
                "WHERE expires_at <= :cutoff ORDER BY expires_at, " + key +
                " LIMIT :capacity) AS candidates"),
                {"cutoff": cutoff, "capacity": batch_size * max_batches})
            db.rollback()
            return count
        total = 0
        for _ in range(max_batches):
            result = db.execute(text(f"DELETE FROM {table} WHERE expires_at <= :cutoff "
                                     f"ORDER BY expires_at, {key} LIMIT :batch"), parameters)
            count = result.rowcount
            db.commit()
            total += count
            if count < batch_size:
                break
        return total
    except Exception:
        db.rollback()
        raise


def maintenance_main(kind, argv=None, factory=None):
    parser = argparse.ArgumentParser(description="Limpieza limitada de autenticación; solo cantidades.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--max-batches", type=int, default=20)
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= 5000 or not 1 <= args.max_batches <= 1000:
        parser.error("batch-size: 1..5000; max-batches: 1..1000")
    if factory is None:
        from app.db.session import SessionLocal
        factory = SessionLocal
    try:
        with factory() as db:
            count = prune(db, kind, dry_run=args.dry_run, batch_size=args.batch_size,
                          max_batches=args.max_batches)
        print(f"{'Candidatos (máximo de esta ejecución)' if args.dry_run else 'Eliminados'}: {count}")
        return 0
    except Exception:
        # Drivers may include SQL parameters in exceptions: never print them.
        print("No se completó la limpieza. Los lotes previamente confirmados se conservan.")
        return 2
