---
status: accepted
---

# A record survives the process: the package serializes it and ships a SQLite store

A run that parks in one process cannot resume in another, because the default `InMemoryRecordStore`
is a dict, and a `UserError` in `_toolset.py` says so. The protocol (`get(key)`, `put(key, record)`)
already admits any backend, but a backend author has to write the deserializer by hand, as the
README's Redis example does in twelve lines that break whenever `Record` gains a field (ADR 0005
added `input` and every custom store had to follow). Two changes. First, the package owns the shape:
`Record.to_dict()` and `Record.from_dict(data)` (with `from_dict` on `StepRecord` and `ItemRecord`
for the rebuild) round-trip a record through a JSON object, so a store moves that object and nothing
else, and the README example shrinks to two lines. `to_dict` is `dataclasses.asdict` passed through
`to_jsonable_python`, so a store never has to know what a step value can be (a custom `Dispatch` may
settle a step to a `datetime` or a tuple; a tuple comes back as a list, which the expression subset
cannot tell apart). `from_dict` rebuilds the nested `StepRecord`s and `ItemRecord`s and requires
exactly the keys `to_dict` writes, since the package wrote them and every field has a default (a
dropped key would otherwise load as a clean, unparked record; found in review). JSON keeps no non-
string dict keys, so a derivation that built a dict keyed by integers comes back keyed by strings
after a durable resume, where the in-memory store would keep the integers; accepted, since the
engine-level fix (JSON-shaping every value at settle) would change first-run semantics for everyone.
Second, the package ships one durable store, `SQLiteRecordStore(path, timeout=5.0)`, in a new module
`_stores.py`, exported from `__init__`. It uses the standard library `sqlite3` with one table,
`records(key TEXT PRIMARY KEY, record TEXT NOT NULL, updated_at TEXT NOT NULL)`, created on first
use; `put` is an `INSERT OR REPLACE` of the JSON object (`ON CONFLICT` needs SQLite 3.24, which a
CPython built against an old distro library may lack; found in review) and `get` parses it or
returns `None`; `updated_at` is written by SQLite as `strftime('%Y-%m-%d %H:%M:%S', 'now')`, its own
UTC text form, so it compares with `datetime('now', ...)`. The store owns one thread (a
`ThreadPoolExecutor` of one worker) and one connection, opened by the first statement on that thread
rather than by the constructor: every statement runs there, so the event loop is never blocked, the
connection is never shared, agents on different event loops can share the store, and `close()` can
drain the queued statements before releasing the connection. The first cut used `asyncio.to_thread`
with a lock; review found that `close()` could then close the connection under a running statement
(a reproducible interpreter crash), that the constructor's open and `CREATE TABLE` blocked the loop
for the busy timeout, and that a fan-out of `put`s parked one default-executor thread per caller.
One connection rather than one per call is what makes `':memory:'` a working store (a fresh
connection to `':memory:'` is a fresh database), and `SQLiteRecordStore(':memory:')` is the test
double for anything that needs a store without the dict. A key is an opaque string to SQLite, so a
script tool's `conversation/name/digest` needs no escaping. `close()` finishes the queued
statements, then releases the connection and the thread; there is no context manager, since the
store's life is the agent's and the connection also closes on collection. `timeout` passes through
to `sqlite3.connect` as the busy timeout. No optional extra: `sqlite3` ships with CPython. The
default store stays in-memory: a default file path would be a silent write to disk; the no-record
`UserError` names `SQLiteRecordStore` as the fix instead. The glossary gains **Key**, the string a
record is stored under, since the protocol, the toolset, and this ADR all say it.

The protocol does not change. `put` stays last-write-wins with no revision, because nothing here
races on a record by design: `run_script` is `sequential=True`, a script tool's record is keyed by
its input, and the one race left (two concurrent calls of one script tool with identical arguments)
was accepted in the item 3 review. callscript's `compareAndSet` exists because its durable runner
claims each execution round so two concurrent resumes cannot both dispatch it; our resume is driven
by Pydantic AI re-issuing one approved call in one run, so the claim has nothing to guard yet. If
that changes (a second resume surface, or a script tool called from two runs in parallel), the
change is `put` answering whether it won and `_run` refusing a lost write; it is recorded here so it
is not re-litigated. Retention is the host's: the protocol has no `delete`, `updated_at` is in the
table so a host can prune with one `DELETE ... WHERE updated_at < ?`, and the README says so. No
expiry inside the package, since a record's useful life is the conversation's and the package does
not know when a conversation ends.

The costs. `Record` gains two methods and its two nested classes one each, which is API surface that
must track every future field; a round-trip test covers it. `_stores.py` is the first module that
does I/O, and it does it through a thread hop per statement, which is negligible next to a model
request; a script tool that completed from no record writes nothing, since the next call would
discard it (found in review). One thread serialises every store call in one process; SQLite's own
file lock serialises writers across processes, and a second process blocks for `timeout` seconds
(SQLite's default, five) before raising `OperationalError`, which surfaces as an unhandled exception
from `run_script`, and when it does after the tools ran the outcome and the approval are lost with
it, since nothing here can carry them without a store; accepted as an infrastructure failure; WAL
mode is not set, since it adds two files next to the database and misbehaves on network filesystems,
and a host that wants it can run the pragma. Two agents in one process can share one store instance;
two processes share the path. `from_dict` being strict means a record written by a newer version
with a field an older version does not know fails to load rather than loading with the field
dropped; the package has no release yet, so there is no compatibility promise to keep, and the
strictness catches a store that mangled the object.

## Considered options

- A JSON file per key: rejected. No dependency either, but a key with slashes needs hashing or
  nested directories, an atomic replace is per file, pruning is a directory walk, and `':memory:'`
  has no equivalent, so tests would keep the dict store as a second double.
- A connection per call, no lock: rejected. Simpler, and thread-safe by construction, but
  `':memory:'` stops working and every `get` pays a connection open.
- One held connection called on the loop with no thread hop: rejected. A local upsert is
  sub-millisecond, but a cold file or a cross-process lock held for `timeout` seconds would stall
  every agent in the process.
- One held connection with `check_same_thread=False`, statements in `asyncio.to_thread` under a
  lock: the first cut; rejected in review for the `close()` race, the blocking constructor, and the
  executor saturation the decision describes. The store's own thread removes all three.
- callscript's `compareAndSet` on a revision: rejected for now, see the decision. It is a protocol
  change (`put` returns `bool`, `Record` carries a revision) that every custom store would have
  to implement, for a race nothing here can run yet.
- A `delete(key)` on the protocol, or a TTL column the store enforces: rejected. Retention policy
  belongs to the host, which knows when a conversation is over; a column and one sentence in the
  README cover it.
- An optional extra (`pydantic-ai-scriptmode[sqlite]`) or a separate package: rejected, `sqlite3`
  is standard library, and an extra with no dependency behind it would only hide the store.
- Serialize with pydantic (`TypeAdapter(Record)`): rejected. It would validate `value` fields as
  `Any` and gain nothing over `asdict` plus `to_jsonable_python`, which the dispatcher already
  uses on every tool result.
- Also make `InMemoryRecordStore` go through `to_dict`/`from_dict` so both stores hold the same
  shape: rejected, the dict store holds the object the engine handed it and a copy would cost
  every call for a behaviour no test needs; the round-trip test proves the shape instead.
