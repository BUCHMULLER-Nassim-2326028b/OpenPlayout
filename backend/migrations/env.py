from alembic import context
from sqlalchemy import create_engine
from app.database import Base
from app.config import Settings

config = context.config
settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
url = config.attributes.get("database_url") or f"sqlite:///{settings.data_dir.resolve() / 'openplayout.db'}"


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url).connect() as connection:
        run(connection)
