
import multiprocessing as mp
import time
from pathlib import Path
from sql3_lite_saver import SQLiteConnectionPool

DB_FILE = Path("multiprocess_demo.db")

def worker(proc_id: int, items: int = 10):
    pool = SQLiteConnectionPool(DB_FILE, enable_retry=True, base_delay=0.5)
    with pool.acquire() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS logs (proc INTEGER, msg TEXT)")
    for i in range(items):
        with pool.acquire() as conn:
            conn.execute("INSERT INTO logs VALUES (?, ?)", (proc_id, f"message {i}"))
            print(f"[Proc {proc_id}] inserted {i}")
        time.sleep(0.1)
    pool.close_all()

def main():
    if DB_FILE.exists():
        DB_FILE.unlink()
    processes = [mp.Process(target=worker, args=(i,)) for i in range(3)]
    for p in processes:
        p.start()
    for p in processes:
        p.join()

    pool = SQLiteConnectionPool(DB_FILE)
    with pool.acquire() as conn:
        rows = list(conn.execute("SELECT COUNT(*) AS n FROM logs"))
        print(f"\n✅ Total inserted rows: {rows[0]['n']}")
    pool.close_all()

if __name__ == "__main__":
    main()
