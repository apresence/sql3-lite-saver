import sqlite3
import threading
import queue
import time
import typing as tp
import atexit
import logging

from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from tenacity import retry, retry_if_exception, stop_after_attempt, wait_chain, wait_fixed
    HAVE_TENACITY = True
except ImportError:
    retry = retry_if_exception = stop_after_attempt = wait_chain = wait_fixed = None
    HAVE_TENACITY = False

'''
@tp.runtime_checkable
class ConnectionLike(tp.Protocol):
    def execute(self, *a: tp.Any, **kw: tp.Any): ...
    def executemany(self, *a: tp.Any, **kw: tp.Any): ...
    def executescript(self, *a: tp.Any, **kw: tp.Any): ...
    def close(self) -> None: ...
'''

class _ConnectionProxy:
    """Lightweight proxy that adds retry to SQLite connection methods with proper type support."""
    def __init__(self, conn: sqlite3.Connection, wrapper: tp.Callable):
        self._conn = conn
        self._wrap = wrapper

    # Explicit methods with retry and proper type hints
    def execute(self, sql: str, parameters: tp.Sequence[tp.Any] = ()) -> sqlite3.Cursor:
        """Execute a single SQL statement with retry logic."""
        return self._wrap(self._conn.execute)(sql, parameters)
    
    def executemany(self, sql: str, seq_of_parameters: tp.Iterable[tp.Sequence[tp.Any]]) -> sqlite3.Cursor:
        """Execute SQL statement multiple times with retry logic."""
        return self._wrap(self._conn.executemany)(sql, seq_of_parameters)
    
    def executescript(self, sql_script: str) -> sqlite3.Cursor:
        """Execute multiple SQL statements with retry logic."""
        return self._wrap(self._conn.executescript)(sql_script)

    # Pass through other commonly used connection methods without retry
    def commit(self) -> None:
        """Commit the current transaction."""
        self._conn.commit()
    
    def rollback(self) -> None:
        """Roll back the current transaction."""
        self._conn.rollback()
    
    def close(self) -> None:
        """Close the connection."""
        self._conn.close()
    
    @property
    def row_factory(self) -> tp.Optional[tp.Callable]:
        """Get/set the row factory for this connection."""
        return self._conn.row_factory
    
    @row_factory.setter
    def row_factory(self, factory: tp.Optional[tp.Callable]) -> None:
        self._conn.row_factory = factory
    
    @property
    def total_changes(self) -> int:
        """Get the total number of changes made to the database."""
        return self._conn.total_changes

    # Fallback for any other attributes/methods
    def __getattr__(self, name: str) -> tp.Any:
        return getattr(self._conn, name)

    # Allow 'with conn:' usage
    def __enter__(self) -> sqlite3.Connection:
        return tp.cast(sqlite3.Connection, self._conn)

    def __exit__(self, exc_type: tp.Optional[tp.Type[BaseException]], 
                 exc_val: tp.Optional[BaseException], 
                 exc_tb: tp.Optional[tp.Any]) -> tp.Optional[bool]:
        return self._conn.__exit__(exc_type, exc_val, exc_tb)

class ConnectionPool:
    def __init__(
        self,
        db_path: Path,
        *,
        max_size: int = 5,
        acquire_timeout: float | None = None,
        enable_retry: bool = True,
        base_delay: float = 1.0,
        max_backoff_total: float = 60.0,
        retry_attempts: int | None = None,
        retry_jitter: float = 0.1,
        auto_cleanup: bool = True,
        read_only: bool = False,
        warmup_callback: tp.Callable[[sqlite3.Connection], None] | None = None,
    ):
        self.db_path = db_path
        self.max_size = max_size
        self.acquire_timeout = acquire_timeout
        self.enable_retry = enable_retry
        self.base_delay = base_delay
        self.max_backoff_total = max_backoff_total
        self.retry_attempts = retry_attempts
        self.retry_jitter = retry_jitter
        self.read_only = read_only
        self.warmup_callback = warmup_callback

        self._pool: "queue.Queue[sqlite3.Connection]" = queue.Queue(max_size)
        self._all_conns: list[sqlite3.Connection] = []
        self._lock = threading.RLock()
        self._wait_count = 0
        self._is_closed = False

        for _ in range(max_size):
            conn = self._create_connection()
            self._pool.put(conn)
            self._all_conns.append(conn)

        if auto_cleanup:
            atexit.register(self._atexit_cleanup)
            logger.debug("Registered atexit cleanup for SQLiteConnectionPool")

        logger.info(f"SQLiteConnectionPool created with max_size={max_size}")

    # ------------------------------------------------------------------
    # Connection creation / validation
    # ------------------------------------------------------------------
    def _create_connection(self) -> sqlite3.Connection:
        uri = f"file:{self.db_path}?mode=ro" if self.read_only else str(self.db_path)
        conn = sqlite3.connect(
            uri,
            timeout=10.0,
            isolation_level=None,       # autocommit
            check_same_thread=False,    # allow cross-thread usage
            uri=self.read_only,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        if self.warmup_callback:
            self.warmup_callback(conn)
        return self._wrap_connection(conn)

    def _validate_connection(self, conn: sqlite3.Connection) -> sqlite3.Connection:
        try:
            # Get the underlying connection if this is a proxy
            underlying_conn = getattr(conn, '_conn', conn)
            underlying_conn.execute("SELECT 1")
            return conn
        except sqlite3.Error:
            logger.warning("Recreating stale SQLite connection")
            # Create new connection without wrapping first
            uri = f"file:{self.db_path}?mode=ro" if self.read_only else str(self.db_path)
            new_conn = sqlite3.connect(
                uri,
                timeout=10.0,
                isolation_level=None,
                check_same_thread=False,
                uri=self.read_only,
            )
            new_conn.row_factory = sqlite3.Row
            new_conn.execute("PRAGMA foreign_keys = ON")
            new_conn.execute("PRAGMA busy_timeout = 10000")
            new_conn.execute("PRAGMA journal_mode = WAL")
            new_conn.execute("PRAGMA synchronous = NORMAL")
            if self.warmup_callback:
                self.warmup_callback(new_conn)
            
            # Now wrap it
            wrapped_conn = self._wrap_connection(new_conn)
            
            with self._lock:
                try:
                    self._all_conns.remove(conn)
                except ValueError:
                    pass
                self._all_conns.append(wrapped_conn)
            return wrapped_conn

    # ------------------------------------------------------------------
    # Retry wrapping
    # ------------------------------------------------------------------
    def _compute_backoff_delays(self) -> list[float]:
        delays, total, d = [], 0.0, self.base_delay
        while total + d <= self.max_backoff_total:
            delays.append(d)
            total += d
            d *= 2
        if total < self.max_backoff_total:
            delays.append(round(self.max_backoff_total - total, 1))
        return delays

    def _build_tenacity_retry(self):
        if not HAVE_TENACITY:
            return None
        
        if tp.TYPE_CHECKING:
            assert retry is not None
            assert retry_if_exception is not None
            assert stop_after_attempt is not None
            assert wait_chain is not None
            assert wait_fixed is not None

        base_delay = self.base_delay
        max_delay = self.max_backoff_total
        jitter = self.retry_jitter

        delays = []
        total = 0.0
        d = base_delay
        while total + d <= max_delay:
            delays.append(d)
            total += d
            d *= 2
        if total < max_delay:
            delays.append(round(max_delay - total, 1))

        waits = [wait_fixed(d).__add__(wait_fixed(jitter)) for d in delays]

        return retry(
            retry=retry_if_exception(lambda e: "locked" in str(e).lower()),
            wait=wait_chain(*waits),
            stop=stop_after_attempt(len(waits)),
            reraise=True,
        )

    def _wrap_with_retry(self, func):
        if not self.enable_retry:
            return func

        if HAVE_TENACITY:
            retry_obj = self._build_tenacity_retry()
            if retry_obj:
                return retry_obj(func)

        delays = self._compute_backoff_delays()
        def wrapper(*args, **kwargs):
            for i, delay in enumerate(delays, 1):
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "locked" not in str(e).lower() or i == len(delays):
                        raise
                    logger.debug(f"DB locked; retry {i}/{len(delays)} in {delay:.1f}s")
                    time.sleep(delay)
        return wrapper

    def _wrap_connection(self, conn: sqlite3.Connection) -> sqlite3.Connection:
        """Return a proxy connection with retry-wrapped methods."""
        return tp.cast(sqlite3.Connection, _ConnectionProxy(conn, self._wrap_with_retry))
    
    
    # ------------------------------------------------------------------
    # Acquire / Try-Acquire context managers
    # ------------------------------------------------------------------
    class _ConnContext:
        def __init__(self, pool: "ConnectionPool", conn: sqlite3.Connection):
            self.pool = pool
            self.conn = conn

        def __enter__(self) -> sqlite3.Connection:
            return self.conn

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.pool._release(self.conn)

    def acquire(self) -> "_ConnContext":
        start = time.perf_counter()
        with self._lock:
            self._wait_count += 1
        try:
            conn = self._pool.get(timeout=self.acquire_timeout)
            conn = self._validate_connection(conn)
            return self._ConnContext(self, conn)
        except queue.Empty:
            raise TimeoutError("No available database connections in pool")
        finally:
            with self._lock:
                self._wait_count -= 1
            elapsed = time.perf_counter() - start
            if elapsed > 0.01:
                logger.debug(f"Waited {elapsed:.2f}s to acquire connection")

    def try_acquire(self) -> "_ConnContext | None":
        try:
            conn = self._pool.get_nowait()
            conn = self._validate_connection(conn)
            logger.debug(f"Non-blocking acquire succeeded (in_use={self.in_use})")
            return self._ConnContext(self, conn)
        except queue.Empty:
            logger.debug("Non-blocking acquire failed (pool full)")
            return None

    def _release(self, conn: sqlite3.Connection):
        self._pool.put(conn)
        logger.debug(f"Released connection (in_use={self.in_use})")

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------
    @property
    def in_use(self) -> int:
        if self._is_closed:
            return 0
        return self.max_size - self._pool.qsize()

    @property
    def available(self) -> int:
        if self._is_closed:
            return 0
        return self._pool.qsize()

    @property
    def wait_count(self) -> int:
        return self._wait_count

    # ------------------------------------------------------------------
    # WAL Checkpoint Management
    # ------------------------------------------------------------------
    def checkpoint(
        self, 
        mode: tp.Literal["PASSIVE", "FULL", "RESTART", "TRUNCATE"] = "PASSIVE"
    ) -> tp.Dict[str, int]:
        """
        Perform a WAL checkpoint to transfer WAL data to the main database file.
        
        Without regular checkpoints, the WAL file grows indefinitely, causing:
        - Wasted disk space (WAL can become massive)
        - Degraded read performance (must scan through entire WAL)
        - Potential file system issues with very large files
        
        Modes (from least to most aggressive):
        - PASSIVE (default): Checkpoint without blocking readers/writers
        - FULL: Checkpoint all frames, may block briefly
        - RESTART: Like FULL, then resets WAL for reuse
        - TRUNCATE: Like RESTART, then truncates WAL file to zero bytes
        
        Returns dict with:
        - busy: Number of pages not checkpointed due to locks (0 = full success)
        - log: Total pages in WAL after checkpoint
        - checkpointed: Pages successfully transferred
        
        See: https://www.sqlite.org/pragma.html#pragma_wal_checkpoint
        """
        with self.acquire() as conn:
            # Get the underlying connection if wrapped
            underlying_conn = getattr(conn, '_conn', conn)
            result = underlying_conn.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
            
            if result:
                return {
                    "busy": result[0],  # Pages not checkpointed due to locks
                    "log": result[1],   # Total pages in WAL
                    "checkpointed": result[2]  # Pages successfully checkpointed
                }
            return {"busy": 0, "log": 0, "checkpointed": 0}

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def close_all(self) -> None:
        """Close and clear all pooled SQLite connections."""
        logger.info("Closing all SQLite connections")
        with self._lock:
            # Close every tracked connection (both pooled and in-use)
            for conn in list(self._all_conns):
                try:
                    # Get the underlying connection if this is a proxy
                    underlying_conn = getattr(conn, '_conn', conn)
                    underlying_conn.close()
                except Exception as e:
                    logger.warning(f"Error closing connection: {e}")

            # Clear the pool completely
            while not self._pool.empty():
                try:
                    self._pool.get_nowait()
                except queue.Empty:
                    break

            # Reset internal structures - leave pool empty for testing
            self._all_conns.clear()
            self._pool = queue.Queue(self.max_size)
            self._wait_count = 0
            self._is_closed = True

        logger.debug("All SQLite connections closed and pool reset")

    def _atexit_cleanup(self):
        try:
            self.close_all()
            logger.debug("SQLiteConnectionPool auto-cleanup complete")
        except Exception as e:
            logger.warning(f"Atexit cleanup failed: {e}")
