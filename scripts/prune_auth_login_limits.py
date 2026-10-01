"""Remove expired login buckets, without disclosing identifiers."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from app.services.auth_pruning import maintenance_main


def main(argv=None):
    return maintenance_main("limits", argv)


if __name__ == "__main__":
    raise SystemExit(main())
