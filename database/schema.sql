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
