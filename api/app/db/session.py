from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"init_command": "SET time_zone='+00:00'"},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    """Proporciona una sesión por request y garantiza su cierre."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
