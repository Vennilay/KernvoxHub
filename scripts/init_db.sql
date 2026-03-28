-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Convert metrics table to hypertable
-- Note: This runs after the table is created by SQLAlchemy
-- The hypertable creation is handled in the application startup
