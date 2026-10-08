# create_database.py

from sqlalchemy import create_engine, text
from myproject.config import DATABASE_URL


# Connect to the PostgreSQL server,
# but NOT to ai_document_intelligence database.
server_url = DATABASE_URL.rsplit("/", 1)[0] + "/postgres"

engine = create_engine(server_url)


database_name = DATABASE_URL.rsplit("/", 1)[1]


with engine.connect() as connection:
    connection.execution_options(isolation_level="AUTOCOMMIT")

    result = connection.execute(
        text("SELECT 1 FROM pg_database WHERE datname = :name"),
        {"name": database_name}
    )

    database_exists = result.scalar() is not None

    if not database_exists:
        connection.execute(
            text(f'CREATE DATABASE "{database_name}"')
        )
        print(f"Database '{database_name}' created.")
    else:
        print(f"Database '{database_name}' already exists.")