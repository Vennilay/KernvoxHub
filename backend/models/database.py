import logging

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def ensure_runtime_schema() -> None:
    if engine.dialect.name != "postgresql":
        return

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE IF EXISTS servers ADD COLUMN IF NOT EXISTS host_key TEXT"))
        connection.execute(text("ALTER TABLE IF EXISTS metrics ALTER COLUMN timestamp SET NOT NULL"))
        connection.execute(
            text(
                """
                DO $$
                DECLARE
                    pk_name text;
                    includes_timestamp boolean := false;
                BEGIN
                    IF to_regclass('public.metrics') IS NULL THEN
                        RETURN;
                    END IF;

                    SELECT tc.constraint_name
                    INTO pk_name
                    FROM information_schema.table_constraints tc
                    WHERE tc.table_schema = 'public'
                      AND tc.table_name = 'metrics'
                      AND tc.constraint_type = 'PRIMARY KEY'
                    LIMIT 1;

                    IF pk_name IS NULL THEN
                        ALTER TABLE public.metrics
                            ADD CONSTRAINT metrics_pkey PRIMARY KEY (id, timestamp);
                        RETURN;
                    END IF;

                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.key_column_usage
                        WHERE table_schema = 'public'
                          AND table_name = 'metrics'
                          AND constraint_name = pk_name
                          AND column_name = 'timestamp'
                    )
                    INTO includes_timestamp;

                    IF NOT includes_timestamp THEN
                        EXECUTE format('ALTER TABLE public.metrics DROP CONSTRAINT %I', pk_name);
                        ALTER TABLE public.metrics
                            ADD CONSTRAINT metrics_pkey PRIMARY KEY (id, timestamp);
                    END IF;
                END
                $$;
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_metrics_id ON metrics (id)"))


def ensure_metrics_hypertable() -> None:
    if engine.dialect.name != "postgresql":
        return

    with engine.begin() as connection:
        extension_installed = connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb')")
        ).scalar()
        if not extension_installed:
            return

        try:
            connection.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF to_regclass('public.metrics') IS NOT NULL THEN
                            PERFORM create_hypertable(
                                'metrics',
                                'timestamp',
                                if_not_exists => TRUE,
                                migrate_data => TRUE
                            );
                        END IF;
                    END
                    $$;
                    """
                )
            )
        except DatabaseError as exc:
            logger.warning("Skipping hypertable conversion: %s", exc)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
