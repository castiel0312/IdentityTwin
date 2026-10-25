from collections.abc import Generator

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema

from app.core.config import settings
from app.models.base import Base
from app.models.evidence import HoneyWorkspaceState

connect_args = {}
if "sqlite" in settings.DATABASE_URL:
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    execution_options={"schema_translate_map": {"honey": None}}
    if "sqlite" in settings.DATABASE_URL
    else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

honey_database_url = settings.HONEY_DB_URL or settings.DATABASE_URL
honey_connect_args = {"check_same_thread": False} if "sqlite" in honey_database_url else {}
honey_engine = create_engine(
    honey_database_url,
    connect_args=honey_connect_args,
    pool_pre_ping=True,
    execution_options={"schema_translate_map": {"honey": None}}
    if "sqlite" in honey_database_url
    else {},
)
HoneySessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=honey_engine)

_SQLITE_EVIDENCE_GUARDS = (
    ("evidence_log", "UPDATE"),
    ("evidence_log", "DELETE"),
    ("evidence_payload", "UPDATE"),
    ("evidence_payload", "DELETE"),
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a transactional database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_honey_db() -> Generator[Session, None, None]:
    """Provide a session bound to the restricted honey database role."""
    db = HoneySessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all database tables (useful for SQLite dev & automated testing)."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(CreateSchema("honey", if_not_exists=True))
    honey_tables = [table for table in Base.metadata.sorted_tables if table.schema == "honey"]
    application_tables = [table for table in Base.metadata.sorted_tables if table.schema != "honey"]
    Base.metadata.create_all(bind=engine, tables=application_tables)
    Base.metadata.create_all(bind=honey_engine, tables=honey_tables)
    if engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            for table, operation in _SQLITE_EVIDENCE_GUARDS:
                trigger_name = f"{table}_reject_{operation.lower()}"
                connection.exec_driver_sql(
                    f"CREATE TRIGGER IF NOT EXISTS {trigger_name} "
                    f"BEFORE {operation} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'evidence records are append-only'); END"
                )


def check_db_ready() -> bool:
    """Verify the application database and honey workspace are reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        with honey_engine.connect() as conn:
            conn.execute(select(HoneyWorkspaceState.session_id).limit(0))
        return True
    except Exception:
        return False
