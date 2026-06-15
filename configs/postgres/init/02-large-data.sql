-- =============================================
-- 02-large-data.sql
-- Реалистичная структура e-commerce (5 связанных таблиц)
-- ~3.7 млн строк всего, FK работают корректно
-- =============================================

-- 1. Категории (5 штук)
CREATE TABLE IF NOT EXISTS categories (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT
);

INSERT INTO categories (name, description) VALUES
('Electronics', 'Gadgets and devices'),
('Clothing',    'Fashion and apparel'),
('Books',       'Literature and education'),
('Home',        'Household items'),
('Sports',      'Sporting goods')
ON CONFLICT (name) DO NOTHING;

-- 2. Продукты (~100 000 строк)
CREATE TABLE IF NOT EXISTS products (
    id            BIGSERIAL PRIMARY KEY,
    category_id   INT NOT NULL REFERENCES categories(id),
    name          TEXT NOT NULL,
    price         NUMERIC(10,2) NOT NULL CHECK (price > 0),
    stock         INT NOT NULL DEFAULT 100 CHECK (stock >= 0)
);

INSERT INTO products (category_id, name, price, stock)
SELECT
    (random()*4)::int + 1,                    -- теперь только 1..5
    'Product ' || i,
    (random()*999.99 + 9.99)::numeric(10,2),
    (random()*500 + 10)::int
FROM generate_series(1, 100000) AS i;

-- 3. Клиенты (~300 000 строк — уменьшил, чтобы быстрее)
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
FROM generate_series(1, 300000) AS i;

-- 4. Заказы (~1 000 000 строк)
CREATE TABLE IF NOT EXISTS orders (
    id          BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(id),
    order_date  TIMESTAMP NOT NULL,
    status      TEXT NOT NULL DEFAULT 'completed'
);

INSERT INTO orders (customer_id, order_date, status)
SELECT
    (random()*299999)::bigint + 1,
    NOW() - (random()*730)::int * INTERVAL '1 day',
    (ARRAY['pending','shipped','completed','cancelled'])[floor(random()*4 + 1)::int]
FROM generate_series(1, 1000000) AS i;

-- 5. Позиции заказов (~1 500 000 строк)
CREATE TABLE IF NOT EXISTS order_items (
    id          BIGSERIAL PRIMARY KEY,
    order_id    BIGINT NOT NULL REFERENCES orders(id),
    product_id  BIGINT NOT NULL REFERENCES products(id),
    quantity    INT NOT NULL CHECK (quantity > 0),
    price       NUMERIC(10,2) NOT NULL CHECK (price > 0)
);

INSERT INTO order_items (order_id, product_id, quantity, price)
SELECT
    (random()*999999)::bigint + 1,
    (random()*99999)::bigint + 1,
    (random()*10)::int + 1,
    (random()*999.99 + 9.99)::numeric(10,2)
FROM generate_series(1, 1500000) AS i;

-- Создаём базовые индексы (пока закомментированы — будем включать поэтапно для демо)
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_order_date ON orders(order_date);
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_items_product_id ON order_items(product_id);

ANALYZE categories, products, customers, orders, order_items;

-- Финальная проверка
SELECT
    (SELECT COUNT(*) FROM categories)     AS categories,
    (SELECT COUNT(*) FROM products)       AS products,
    (SELECT COUNT(*) FROM customers)      AS customers,
    (SELECT COUNT(*) FROM orders)         AS orders,
    (SELECT COUNT(*) FROM order_items)    AS order_items,
    pg_size_pretty(pg_database_size(current_database())) AS total_db_size;