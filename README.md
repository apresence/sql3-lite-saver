# sql3-lite-saver

[![CI](https://github.com/apresence/sql3-lite-saver/actions/workflows/ci.yml/badge.svg)](https://github.com/apresence/sql3-lite-saver/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

*A Jedi-approved SQLite connection pool, strong in the **WAL** side of the Force.*

> We make your Bad Batch good.

---

## Why You Need a Connection Pool

SQLite is fast and embedded, but it isn't built for many simultaneous writers.  
Without pooling, each connection must reinitialize SQLite state, and you'll quickly see:

> `sqlite3.OperationalError: database is locked`

**sql3-lite-saver** helps by:
- Reusing a fixed number of open connections
- Enabling WAL (Write-Ahead Logging) automatically
- Retrying transparently with exponential backoff (optional Tenacity support)
- Supporting multi-threaded and multi-process workloads safely

---

## ⚠️ IMPORTANT: WAL Checkpoint Maintenance

**If you use WAL mode (enabled by default), you MUST run periodic checkpoints** or your database files can bloat over time.

Without checkpoints:
- WAL file can grow unbounded
- Read performance can steadily degrade

See the [WAL Checkpoint Management](#wal-checkpoint-management) section below for details.

---

## Installation

### From PyPI

```bash
pip install sql3-lite-saver
```

### With optional retry engine (Tenacity)

```bash
pip install sql3-lite-saver[retry]
```

### For development (editable)

```bash
pip install -e .[dev,retry]
```

### Extras explained

| Extra | Purpose | What's Included |
|------|---------|------------------|
| `retry` | Adds [Tenacity](https://tenacity.readthedocs.io) for advanced retry control | `tenacity>=8.0` |
| `dev` | Developer tools | `ruff`, `pytest` (optional), `twine`, `build` |

---

## Example

```python
from pathlib import Path
from sql3_lite_saver import ConnectionPool

pool = ConnectionPool(Path("app.db"), max_size=3)

with pool.acquire() as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS demo (id, msg)")
    conn.execute("INSERT INTO demo VALUES (?, ?)", (1, "hello there"))

with pool.acquire() as conn:
    print([dict(r) for r in conn.execute("SELECT * FROM demo").fetchall()])
```

---

## Advanced Retry with Tenacity

When you install Tenacity (`pip install sql3-lite-saver[retry]`), **sql3-lite-saver** can use it for retry logic.  
You can fine-tune retry behavior with parameters:

```python
pool = ConnectionPool(
    Path("app.db"),
    enable_retry=True,
    retry_attempts=8,
    base_delay=0.5,
    retry_jitter=0.25,
)
```

Without Tenacity installed, it falls back to built-in exponential backoff (`1s, 2s, 4s, ...` up to 60s).

---

## WAL Checkpoint Management

### Why Checkpoints Matter

When using WAL (Write-Ahead Logging), SQLite writes go to a **separate file** (`app.db-wal`) instead of the main database (`app.db`). **Without regular checkpoints**, the WAL file can grow indefinitely, causing:

- **Disk space bloat** - WAL can balloon to gigabytes
- **Degraded read performance** - SQLite may scan a larger WAL on reads
- **File system issues** - Very large WAL files can cause problems

Checkpoints transfer WAL data from `app.db-wal` back to the main `app.db` file, resetting the WAL.

**Additional database files created by WAL mode:**
- `app.db-wal` - Write-Ahead Log
- `app.db-shm` - Shared memory for coordination

### Checkpoint Modes

```python
from pathlib import Path
from sql3_lite_saver import ConnectionPool

pool = ConnectionPool(Path("app.db"))

# PASSIVE (default) - Non-blocking, checkpoint what you can
result = pool.checkpoint("PASSIVE")

# FULL - Checkpoint all frames, may block briefly
result = pool.checkpoint("FULL")

# RESTART - Like FULL, then reset WAL for reuse
result = pool.checkpoint("RESTART")

# TRUNCATE - Like RESTART, then shrink WAL to zero bytes (reclaim disk space)
result = pool.checkpoint("TRUNCATE")

print(result)
# {'busy': 0, 'log': 1024, 'checkpointed': 1024}
# busy=0 means full success, >0 means some pages couldn't be checkpointed
```

### When to Checkpoint

- **Periodic background task** - Every hour with `PASSIVE` (or `TRUNCATE` if you want to reclaim space)
- **Before backups** - Use `TRUNCATE` to minimize backup size
- **Low-traffic periods** - `TRUNCATE` during maintenance windows
- **On application shutdown** - Final `TRUNCATE` to clean up

### References

- [SQLite WAL Mode Documentation](https://www.sqlite.org/wal.html)
- [PRAGMA wal_checkpoint](https://www.sqlite.org/pragma.html#pragma_wal_checkpoint)
- [Performance tuning with checkpoints](https://www.sqlite.org/wal.html#performance_considerations)

---

## Testing

If you use `pytest`:

```bash
pytest -q
```

Or with the standard library `unittest`:

```bash
python -m unittest discover -s tests -v
```

---

## Developer Shortcuts

```bash
make install-dev   # editable install with dev + retry deps
make install-prod  # editable install (minimal)
make lint          # run Ruff
make test          # run tests
make release       # build + twine upload
```

---

## License

MIT © 2025 [@apresence](https://github.com/apresence)
