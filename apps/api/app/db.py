from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings


class Base(DeclarativeBase):
    pass


# hide_parameters: database errors in the logs never carry row values (evidence text, facts).
# statement_timeout: every statement, on every connection (docs/SECURITY_P2_5.md §7).
# On Vercel (docs/ADR-006) each function instance is short-lived and DATABASE_URL is an external
# transaction pooler: keep no pool here, and no server-side prepared statements, which a
# transaction pooler cannot carry from one transaction to the next.
_serverless = get_settings().vercel
engine = create_engine(
    get_settings().database_url,
    pool_pre_ping=True,
    hide_parameters=True,
    connect_args={
        "options": f"-c statement_timeout={get_settings().db_statement_timeout_ms}",
        **({"prepare_threshold": None} if _serverless else {}),
    },
    **({"poolclass": NullPool} if _serverless else {}),
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with SessionLocal() as session:
        yield session
