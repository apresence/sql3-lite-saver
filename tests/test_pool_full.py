import unittest
import threading
from pathlib import Path
from sql3_lite_saver import SQLiteConnectionPool

DB_FILE = Path("test_pool.db")


class TestSQLiteConnectionPool(unittest.TestCase):
    def setUp(self):
        if DB_FILE.exists():
            DB_FILE.unlink()
        self.pool = SQLiteConnectionPool(DB_FILE, max_size=3, enable_retry=True)

    def tearDown(self):
        self.pool.close_all()
        if DB_FILE.exists():
            DB_FILE.unlink()

    def test_basic_insert_and_select(self):
        with self.pool.acquire() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER, msg TEXT)")
            conn.execute("INSERT INTO t VALUES (?, ?)", (1, "hello"))
        with self.pool.acquire() as conn:
            result = [dict(r) for r in conn.execute("SELECT * FROM t")]
        self.assertEqual(result, [{"id": 1, "msg": "hello"}])

    def test_connection_reuse(self):
        conns = []
        for _ in range(3):
            with self.pool.acquire() as conn:
                conns.append(id(conn))
        self.assertEqual(len(set(conns)), 3)

    def test_pool_exhaustion(self):
        held = []
        for _ in range(3):
            ctx = self.pool.try_acquire()
            self.assertIsNotNone(ctx)
            held.append(ctx)
        ctx_fail = self.pool.try_acquire()
        self.assertIsNone(ctx_fail)
        for c in held:
            c.__exit__(None, None, None)

    def test_multithreaded_access(self):
        results = []
        def worker(tid):
            for i in range(10):
                with self.pool.acquire() as conn:
                    conn.execute("INSERT OR IGNORE INTO t VALUES (?, ?)", (tid * 100 + i, f"t{tid}-{i}"))
                    results.append(i)

        with self.pool.acquire() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, msg TEXT)")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with self.pool.acquire() as conn:
            rowcount = conn.execute("SELECT COUNT(*) AS n FROM t").fetchone()["n"]
        self.assertGreaterEqual(rowcount, 40)

    def test_cleanup(self):
        self.pool.close_all()
        self.assertEqual(self.pool.in_use, 0)
        self.assertEqual(len(self.pool._all_conns), 0)


if __name__ == "__main__":
    unittest.main()
