-- Idempotent D-LUMEN schema. Does not delete or truncate existing data.
CREATE TABLE IF NOT EXISTS viirs_monthly (
    id BIGSERIAL PRIMARY KEY,
    year INTEGER NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    filename TEXT NOT NULL,
    valid_pixels BIGINT NOT NULL CHECK (valid_pixels >= 0),
    mean_radiance DOUBLE PRECISION,
    min_radiance DOUBLE PRECISION,
    max_radiance DOUBLE PRECISION,
    sum_radiance DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT viirs_monthly_year_month_key UNIQUE (year, month)
);

CREATE INDEX IF NOT EXISTS idx_viirs_monthly_year ON viirs_monthly (year);
CREATE INDEX IF NOT EXISTS idx_viirs_monthly_month ON viirs_monthly (month);
CREATE INDEX IF NOT EXISTS idx_viirs_monthly_mean ON viirs_monthly (mean_radiance);

-- Spatial chunks keep the workload database-backed while giving each Worker
-- enough independent records to use all local CPU cores.
CREATE TABLE IF NOT EXISTS viirs_grid_chunks (
    id BIGSERIAL PRIMARY KEY,
    year INTEGER NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    filename TEXT NOT NULL,
    row_off INTEGER NOT NULL,
    col_off INTEGER NOT NULL,
    width INTEGER NOT NULL CHECK (width > 0),
    height INTEGER NOT NULL CHECK (height > 0),
    valid_pixels BIGINT NOT NULL CHECK (valid_pixels > 0),
    mean_radiance DOUBLE PRECISION NOT NULL,
    min_radiance DOUBLE PRECISION NOT NULL,
    max_radiance DOUBLE PRECISION NOT NULL,
    sum_radiance DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT viirs_grid_chunks_position_key
        UNIQUE (year, month, row_off, col_off)
);

CREATE INDEX IF NOT EXISTS idx_viirs_grid_period
    ON viirs_grid_chunks (year, month);
CREATE INDEX IF NOT EXISTS idx_viirs_grid_mean
    ON viirs_grid_chunks (mean_radiance);
