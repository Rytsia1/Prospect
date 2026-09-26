from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.config import get_settings
from app.db import Base

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)

connectable = create_engine(get_settings().database_url)
with connectable.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
