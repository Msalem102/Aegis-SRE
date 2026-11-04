-- ====================================================================
-- PostgreSQL Failure Mode Simulation: Database Setup & Data Seeding
-- ====================================================================

-- 1. Create an unprivileged user for the application pool if not exists
DO
$do$
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_catalog.pg_roles
      WHERE rolname = 'app_user') THEN
      CREATE USER app_user WITH PASSWORD 'app_secret';
   END IF;
END
$do$;

-- 2. Schema definition
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

CREATE TABLE customers (
    customer_id SERIAL PRIMARY KEY,
    name TEXT
);

CREATE TABLE products (
    product_id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    stock INT NOT NULL DEFAULT 1000
);

CREATE TABLE orders (
    order_id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(customer_id),
    status TEXT DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT NOW()
);

-- THE TRAP: Foreign keys are deliberately left unindexed
-- This forces PostgreSQL to perform full sequential scans on 50,000+ items during order lookups
CREATE TABLE order_items (
    item_id SERIAL PRIMARY KEY,
    order_id INT REFERENCES orders(order_id),
    product_id INT REFERENCES products(product_id),
    quantity INT NOT NULL
);

-- 3. Seed realistic volume
-- 1,000 customers
INSERT INTO customers (name)
SELECT 'Customer ' || g FROM generate_series(1, 1000) g;

-- 4 core catalog products
INSERT INTO products (name, price, stock) VALUES
('Espresso Blend', 14.50, 500),
('Cold Brew Bottle', 5.00, 300),
('Pour-Over Dripper', 28.00, 150),
('Ceramic Mug', 12.00, 400);

-- 10,000 historical orders
INSERT INTO orders (customer_id, status)
SELECT (random() * 999 + 1)::int, 'COMPLETED'
FROM generate_series(1, 10000);

-- 50,000 order items across 10,000 orders (unindexed)
INSERT INTO order_items (order_id, product_id, quantity)
SELECT (random() * 9999 + 1)::int, (random() * 3 + 1)::int, (random() * 2 + 1)::int
FROM generate_series(1, 50000);

-- 4. Extensions & Permissions
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO app_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO app_user;
GRANT EXECUTE ON FUNCTION pg_stat_statements_reset() TO app_user;
