"""Remove sessions expired at least 24 hours ago, in bounded transactions."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from app.services.auth_pruning import maintenance_main


def main(argv=None):
    return maintenance_main("sessions", argv)


if __name__ == "__main__":
    raise SystemExit(main())
