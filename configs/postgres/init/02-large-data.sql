CREATE TABLE IF NOT EXISTS categories (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT
);

INSERT INTO categories (name, description) VALUES
('Electronics', 'Gadgets and devices'),
('Clothing', 'Fashion and apparel'),
('Books', 'Literature and education'),
('Home', 'Household items'),
('Sports', 'Sporting goods')
ON CONFLICT DO NOTHING;

-- 2. Продукты (~100 000 строк)
CREATE TABLE IF NOT EXISTS products (
    id            BIGSERIAL PRIMARY KEY,
    category_id   INT REFERENCES categories(id),
    name          TEXT NOT NULL,
    price         NUMERIC(10,2) NOT NULL,
    stock         INT NOT NULL DEFAULT 100
);

INSERT INTO products (category_id, name, price, stock)
SELECT
    (random()*5)::int + 1,
    'Product ' || i,
    (random()*999.99 + 10)::numeric(10,2),
    (random()*500)::int
FROM generate_series(1, 100000) AS i;

-- 3. Клиенты (~500 000 строк)
CREATE TABLE IF NOT EXISTS customers (
    id         BIGSERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    email      TEXT UNIQUE,
    registered TIMESTAMP DEFAULT NOW()
);

INSERT INTO customers (name, email, registered)
SELECT
    'Customer ' || i,
    'user' || i || '@example.com',
    NOW() - (random()*730)::int * INTERVAL '1 day'
FROM generate_series(1, 500000) AS i;

-- 4. Заказы (~1 500 000 строк)
CREATE TABLE IF NOT EXISTS orders (
    id          BIGSERIAL PRIMARY KEY,
    customer_id BIGINT REFERENCES customers(id),
    order_date  TIMESTAMP NOT NULL,
    status      TEXT NOT NULL DEFAULT 'completed'
);

INSERT INTO orders (customer_id, order_date, status)
SELECT
    (random()*499999)::bigint + 1,
    NOW() - (random()*730)::int * INTERVAL '1 day',
    (ARRAY['pending','shipped','completed','cancelled'])[floor(random()*4 + 1)::int]
FROM generate_series(1, 1500000) AS i;

-- 5. Позиции заказов (~2 000 000 строк) — самая большая таблица
CREATE TABLE IF NOT EXISTS order_items (
    id          BIGSERIAL PRIMARY KEY,
    order_id    BIGINT REFERENCES orders(id),
    product_id  BIGINT REFERENCES products(id),
    quantity    INT NOT NULL,
    price       NUMERIC(10,2) NOT NULL
);

INSERT INTO order_items (order_id, product_id, quantity, price)
SELECT
    (random()*1499999)::bigint + 1,
    (random()*99999)::bigint + 1,
    (random()*10)::int + 1,
    (random()*999.99 + 10)::numeric(10,2)
FROM generate_series(1, 2000000) AS i;

-- Создаём полезные индексы (пока закомментированы — позже раскомментируем и покажем разницу)
-- CREATE INDEX idx_orders_customer_id ON orders(customer_id);
-- CREATE INDEX idx_orders_order_date ON orders(order_date);
-- CREATE INDEX idx_order_items_order_id ON order_items(order_id);
-- CREATE INDEX idx_order_items_product_id ON order_items(product_id);

ANALYZE categories, products, customers, orders, order_items;

-- Проверка
SELECT
    (SELECT COUNT(*) FROM categories) AS cat,
    (SELECT COUNT(*) FROM products) AS prod,
    (SELECT COUNT(*) FROM customers) AS cust,
    (SELECT COUNT(*) FROM orders) AS ord,
    (SELECT COUNT(*) FROM order_items) AS items,
    pg_size_pretty(pg_database_size(current_database())) AS total_db_size;