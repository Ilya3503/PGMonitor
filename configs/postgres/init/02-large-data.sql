CREATE TABLE IF NOT EXISTS large_orders (
    id              BIGSERIAL PRIMARY KEY,
    customer_id     INT NOT NULL,
    order_date      TIMESTAMP NOT NULL,
    amount          NUMERIC(12,2) NOT NULL,
    status          TEXT NOT NULL,
    product_code    TEXT,
    region          TEXT
);


INSERT INTO large_orders (customer_id, order_date, amount, status, product_code, region)
SELECT
    (random() * 999999)::int + 1 AS customer_id,
    NOW() - (random() * 365 * 5)::int * INTERVAL '1 day' AS order_date,
    (random() * 9999.99)::numeric(12,2) AS amount,
    (ARRAY['pending', 'shipped', 'delivered', 'cancelled'])[floor(random()*4 + 1)::int] AS status,
    'PROD-' || (random() * 99999)::int AS product_code,
    (ARRAY['Moscow', 'SPb', 'Novosibirsk', 'Ekaterinburg', 'Kazan'])[floor(random()*5 + 1)::int] AS region
FROM generate_series(1, 3000000);



ANALYZE large_orders;

SELECT
    pg_size_pretty(pg_total_relation_size('large_orders')) AS total_size,
    (SELECT COUNT(*) FROM large_orders) AS row_count;