from fastapi import FastAPI
import asyncpg
import asyncio
import random
from datetime import datetime

app = FastAPI(title="Load Simulator for PostgreSQL")

# Пул подключений
pool = None


@app.on_event("startup")
async def startup():
    global pool
    pool = await asyncpg.create_pool(
        user="admin",
        password="admin",
        database="dvdrental",
        host="postgres",
        min_size=5,
        max_size=20
    )


@app.on_event("shutdown")
async def shutdown():
    if pool:
        await pool.close()


# === Эндпоинты для создания нагрузки ===

@app.get("/simple")
async def simple_query():
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"status": "ok"}


@app.get("/medium")
async def medium_query():
    async with pool.acquire() as conn:
        await conn.fetch(
            "SELECT * FROM products WHERE price BETWEEN $1 AND $2 LIMIT 100",
            random.uniform(100, 500),
            random.uniform(500, 900)
        )
    return {"status": "ok"}


@app.get("/heavy")
async def heavy_query():
    """Самый тяжёлый запрос — имитирует отчёт"""
    async with pool.acquire() as conn:
        await conn.fetch(
            """
            SELECT 
                c.name as category,
                COUNT(oi.id) as items_sold,
                SUM(oi.quantity * oi.price) as revenue
            FROM categories c
            JOIN products p ON p.category_id = c.id
            JOIN order_items oi ON oi.product_id = p.id
            JOIN orders o ON o.id = oi.order_id
            WHERE o.order_date > NOW() - INTERVAL '2 years'
            GROUP BY c.name
            ORDER BY revenue DESC
            """
        )
    return {"status": "ok"}


# Запуск нагрузки в фоне
@app.get("/load/{intensity}")
async def start_load(intensity: int = 50):
    """intensity от 10 до 200 — количество одновременных запросов в секунду"""
    asyncio.create_task(generate_load(intensity))
    return {"message": f"Started load with intensity {intensity}"}


async def generate_load(intensity: int):
    while True:
        tasks = []
        for _ in range(min(8, intensity//20)):
            r = random.random()
            if r < 0.4:
                tasks.append(asyncio.create_task(simple_query()))
            elif r < 0.8:
                tasks.append(asyncio.create_task(medium_query()))
            else:
                tasks.append(asyncio.create_task(heavy_query()))

        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(1)