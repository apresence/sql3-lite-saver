import sqlite3
import threading
import time
from pathlib import Path
from sql3_lite_saver import SQLiteConnectionPool

DB_FILE = Path("tenacity_demo.db")

pool = SQLiteConnectionPool(DB_FILE, enable_retry=True, base_delay=0.5, retry_attempts=5)

with pool.acquire() as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS demo (id INTEGER, msg TEXT)")
    conn.execute("DELETE FROM demo")

def writer():
    with pool.acquire() as conn:
        for i in range(5):
            conn.execute("INSERT INTO demo VALUES (?, ?)", (i, f"thread1-{i}"))
            time.sleep(0.3)

def reader():
    # simulate read contention
    with pool.acquire() as conn:
        for i in range(5):
            rows = list(conn.execute("SELECT * FROM demo"))
            print(f"[Reader] rows={len(rows)}")
            time.sleep(0.3)

t1 = threading.Thread(target=writer)
t2 = threading.Thread(target=reader)

t1.start(); t2.start()
t1.join(); t2.join()

with pool.acquire() as conn:
    print(f"Final rows: {conn.execute('SELECT COUNT(*) FROM demo').fetchone()[0]}")
