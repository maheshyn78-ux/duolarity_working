from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_url = get_settings().database_url
_is_sqlite = _url.startswith("sqlite")
if _is_sqlite and ":memory:" not in _url:
    import os

    _path = _url.split("sqlite:///", 1)[-1]
    if os.path.dirname(_path):
        os.makedirs(os.path.dirname(_path), exist_ok=True)
engine = create_engine(
    _url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):  # allow concurrent reads while a background job writes
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
