from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from myproject.config import DATABASE_URL


engine = create_engine(DATABASE_URL)


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False
)


class Base(DeclarativeBase):
    pass