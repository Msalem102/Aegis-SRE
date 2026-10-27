-- Production Schema: E-Commerce / Fintech Orders
-- Table size in production: ~1,000,000 rows

CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    status VARCHAR(32) NOT NULL, -- 'completed', 'pending', 'cancelled', 'processing'
    total_amount NUMERIC(10, 2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    shipping_address TEXT,
    metadata JSONB
);

-- Existing Indexes in Production (Notice: No index on user_id or status!)
-- Only orders_pkey (id) exists.
