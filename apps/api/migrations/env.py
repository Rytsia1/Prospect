from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app import models  # noqa: F401  (registers tables on Base.metadata)
from app.config import get_settings
from app.db import Base

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)

connectable = create_engine(get_settings().database_url)
with connectable.connect() as connection:
    # One transaction per revision: PostgreSQL only lets a later revision use an enum value that
    # an earlier one added (ALTER TYPE ... ADD VALUE) once that revision has committed.
    context.configure(
        connection=connection, target_metadata=Base.metadata, transaction_per_migration=True
    )
    with context.begin_transaction():
        context.run_migrations()
