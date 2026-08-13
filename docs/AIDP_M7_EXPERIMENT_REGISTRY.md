# AIDP M7 — Research Experiment Registry & Lineage System

The authoritative source of truth for every research experiment. Any run recorded
today can be reproduced years later from stored metadata alone — no raw datasets,
no manually-named output folders. Additive; M1–M6 APIs untouched.

Module: `src/mentisrex/research/experiment_registry/` · Store:
`data/research_registry.duckdb`.

```python
reg = ExperimentRegistry()
exp = reg.start_experiment("momentum_v3", parameters={"lookback": 252, "top": 50},
                           features=["market_cap", "roe"], dataset_versions=versions)
# ... run the backtest ...
reg.finish_experiment(exp, metrics={"Sharpe": 1.8, "MaxDrawdown": -0.21})
cfg = reg.reproduce(exp.experiment_id)   # ready-to-run definition, years later
```

## Architecture

Eight small files, one responsibility each:

| File | Responsibility |
|---|---|
| `models.py` | `Experiment` dataclass (metadata + versions + params + features + metrics + artifacts) |
| `hashing.py` | deterministic metadata fingerprints (never hashes raw data) |
| `lineage.py` | automatic git/interpreter/OS + dataset-version capture |
| `storage.py` | DuckDB — 6 tables, read/write |
| `validation.py` | duplicate detection by fingerprint |
| `quality.py` | completeness checks |
| `engine.py` | public API (`ExperimentRegistry`) |
| `__init__.py` | exports |

Native DuckDB, deterministic, lightweight — **no MLflow / W&B / external tracker**.
It reuses the platform's own conventions (the append-only-row-count version signal
from M6, the DuckDB store pattern from M1–M6) rather than importing a
framework.

### Relationship to the existing `research/store.py`

The pre-existing `ResearchStore` records hypothesis→trial verdicts for the
discovery loop. This registry is a distinct, heavier capability: full lineage,
metadata fingerprints, reproduction, and cross-experiment comparison, in its own
database (`research_registry.duckdb`). They do not share tables and neither
duplicates the other's metadata at runtime.

## Lineage model

Everything reproducible-but-invisible is captured automatically at
`start_experiment`, no manual entry:

- **Code** — `git rev-parse HEAD` + branch (best-effort; absence flagged by quality).
- **Environment** — Python version, `platform.platform()`, hostname, OS user.
- **Timing** — created/started at start; finished + `duration_seconds` at finish.
- **Data** — the seven dataset versions (below).
- **Seed** — `random_seed` passed through so the RNG state is reproducible.

## Dataset fingerprints

Fingerprints are computed over **metadata, never raw datasets** (the spec's
constraint and the only thing that scales). The seven versions:

| Version | Source |
|---|---|
| `prices_version` | `raw_ohlcv` row count (append-only) |
| `fundamentals_version` | `fundamental_facts` row count |
| `insiders_version` | `insider_transactions` row count |
| `universe_version` | `security_identity_history` row count (drives the universe) |
| `securitymaster_version` | `security_master` row count |
| `feature_registry_version` | content hash of the M6 `FEATURES` registry |
| `research_matrix_version` | **derived** — hash of the six above |

The research matrix has no independent state (it's a deterministic view over the
other stores), so its version is a pure function of them — captured, never stored
twice. All stores are append-only, so a row count is a monotonic version: any
ingest changes the count, changes the fingerprint.

`lineage.versions_from_stores(prices=…, fundamentals=…, …)` reads these straight
off the live store handles; `lineage.dataset_versions(...)` builds them from
explicit values (tests, replay).

## Hashing strategy

`blake2b` (16-byte digest) over canonical JSON (`sort_keys=True`, compact
separators). One rule makes everything order-independent: **dict keys are sorted,
list order is preserved** (a parameter set is unordered; a feature list is treated
as a set via `sorted`).

- `hash_params({"lookback":252,"top":50}) == hash_params({"top":50,"lookback":252})`
  — and recursively for nested dicts.
- `dataset_fingerprint` = hash of the version dict.
- `experiment_fingerprint` = hash of `{dataset_fingerprint, feature_set_hash,
  parameter_hash}` — the full run identity, and the duplicate-detection key.

## Experiment lifecycle

```
start_experiment → running
   ├─ finish_experiment(metrics, artifacts) → finished  (duration computed)
   └─ fail_experiment(error)                → failed     (exception text recorded)
```

`fail_experiment` records `status=failed` + the exception type/message and leaves
the registry fully consistent — a subsequent `start_experiment` works normally
(proven by the failure-path test).

### Duplicate handling

On `start_experiment` the fingerprint is looked up; if a canonical experiment
already has it, the new one is tagged `duplicate_of=<original_id>` (not rejected —
intentional re-runs are legal and traceable). "Same data + same features + same
parameters (any ordering)" ⇒ duplicate.

## Public API

`start_experiment` · `finish_experiment` · `fail_experiment` · `load(id)` ·
`latest()` · `search(name=/status=/git_commit=/fingerprint=)` ·
`compare(a, b)` → metric deltas + what-changed flags · `reproduce(id)` → a
ready-to-run definition (dataset versions, feature list, parameters, matrix
version, seed, commit). `quality.check(exp)` reports completeness issues.

## Reproduction guarantees

`reproduce(id)` reconstructs the exact configuration from stored metadata; feeding
it back into `start_experiment` yields the identical fingerprint (tested). Because
dataset versions are append-only counts and the git commit is pinned, "reproduce"
means: check out `git_commit`, replay the stores to the recorded versions, request
the recorded features + parameters — and you are guaranteed the same inputs the
original run saw, with no look-ahead (the PIT gates live in M1–M6).

## Schema (6 tables, `data/research_registry.duckdb`)

`experiments` (metadata + lineage + `fingerprint`/`parameter_hash`/`duplicate_of`/
`error`), `dataset_versions`, `parameter_sets` (name/json-value rows),
`feature_sets`, `performance_metrics`, `artifacts` (type/location/hash). Indexed on
`fingerprint` (duplicate lookup) and `created_at` (latest/search).

## Benchmarks (`scripts/benchmark_registry.py`, 100,000 experiments)

- **lookup 5.69 ms** (target < 20 ms) — PK + indexed satellite reads, flat in N.
- search 6.21 ms · compare 10.60 ms (at 100k rows).
- insert is API-driven (start+finish per experiment). DuckDB is columnar, so
  single-row inserts are deliberately not its fast path; the registry's real
  workload is one experiment at a time (~1–2 ms/op), not bulk. Bulk seeding is not
  a design goal.

## Tests (`tests/research/test_registry.py`, 9, all offline)

start-metadata · finish-duration · order-independent param hash · stable dataset
fingerprint · duplicate detection · reproduce-identical-config · search · compare
metric deltas · failure path without corruption. Full suite: **96 passed, 2
skipped** (87 market_data + 9 registry), zero regressions.

## Known limitations / Skipped

- **Dataset versions are row-count signals, not content hashes.** They detect any
  append (the append-only stores never mutate in place), but not a hypothetical
  in-place edit of an existing row. Unblocked by a per-store content checksum if a
  mutable store is ever introduced — none exists today.
- **`reproduce` returns a definition, it does not re-execute.** Re-running is the
  caller's job (check out the commit, replay stores, call `start_experiment` with
  the returned config). Auto-replay would couple the registry to the backtest
  runner — deferred to M8.
- **`random_seed` is recorded, not enforced.** The registry stores the seed; the
  strategy code must actually seed its RNG with it.
- **Artifact hashes are supplied by the caller.** The registry stores
  `artifact_hash`; it does not read artifact files to compute them (keeps it
  decoupled from artifact storage / filesystem).
- **Git lineage is best-effort.** Outside a git checkout, `git_commit` is null and
  `quality.check` flags `missing_git_commit`.

## Future extensions

- **Auto-replay reproduction** — wire `reproduce` into the backtest runner so an
  experiment re-executes from its stored definition end-to-end.
- **Content checksums** if a mutable data source is added.
- **Artifact store integration** — compute + verify `artifact_hash` against a
  parquet/object store (the M6 feature-store persistence path).
- **Lineage graph** — link experiments to the parent experiment they were derived
  from for full research provenance.
