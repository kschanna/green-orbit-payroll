import os

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker


if os.getenv("CLOUD_SQL_CONNECTION_NAME"):
    DATABASE_URL = URL.create(
        drivername="postgresql+psycopg",
        username=os.getenv("DB_USER", "green_orbit_app"),
        password=os.environ["DB_PASSWORD"],
        database=os.getenv("DB_NAME", "green_orbit_payroll"),
        query={
            "host": f"/cloudsql/{os.environ['CLOUD_SQL_CONNECTION_NAME']}"
        },
    )
else:
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg:///green_orbit_payroll"
    )


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(bind=engine)