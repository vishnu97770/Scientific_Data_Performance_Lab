# Research notes

Status: **researched** (2026-10-13). Nothing here is a project decision; decisions live in
`docs/architecture/PROPOSAL.md` once approved.

Legend for the *Type* column:
**Fact** = stated by the cited primary source ·
**Rec** = design recommendation derived from facts ·
**Assumption** = not verified at a source ·
**Future** = deferred possibility.

Items the fetched source pages did *not* state are listed explicitly in
[Gaps and unverified items](#gaps-and-unverified-items) rather than silently filled in.

---

## 1. NumPy storage and parsing

| # | Claim / question | Finding | Source | Why it matters | Type |
|---|---|---|---|---|---|
| N1 | What does `.npy` store? | A single array with dtype, shape and Fortran-order recorded in an ASCII-dict header; data bytes follow. Header is padded so the preamble is a multiple of 64 bytes. Works across architectures. | <https://numpy.org/doc/stable/reference/generated/numpy.lib.format.html> | `.npy` needs no text parsing; load is header parse + raw read. | Fact |
| N2 | Can `.npy` hold mixed-type tabular data? | Yes, as a structured (record) array; "all NumPy arrays including nested record arrays". Fields with empty names are renamed `f0, f1…`. | same | Defines the MVP `.npy` layout: one structured array (row-wise records). | Fact |
| N3 | Memory mapping | `.npy` supports memory-mapping (`open_memmap`); object arrays do not. | same; <https://numpy.org/doc/stable/reference/generated/numpy.load.html> | Mmap is a different workload from a full read; excluded from MVP. | Fact |
| N4 | What is `.npz`? | A zip archive whose members are `.npy` files, one per named array. `savez` = uncompressed; `savez_compressed` = `ZIP_DEFLATED`. | <https://numpy.org/doc/stable/reference/generated/numpy.savez_compressed.html> | Gives the MVP's uncompressed/compressed column-wise variants; compression costs CPU for size. | Fact |
| N5 | `np.load` on `.npz` | Returns an `NpzFile` (dict-like) that **must be closed** to avoid leaking file descriptors; use a context manager. | <https://numpy.org/doc/stable/reference/generated/numpy.load.html> | Loader must close the archive inside the timed region's scope and materialise arrays before returning. | Fact |
| N6 | `allow_pickle` | Default `False`; object arrays raise `ValueError`. Pickle is not secure against malicious data. | same | Loaders keep the default; schema has no object dtypes. | Fact |
| N7 | Text parsing API | `numpy.loadtxt` is described as "a fast reader for simply formatted files", supports structured `dtype`, `usecols`, `max_rows`. `genfromtxt` is for files with missing data. | <https://numpy.org/doc/stable/reference/generated/numpy.loadtxt.html>, <https://numpy.org/doc/stable/reference/generated/numpy.genfromtxt.html> | MVP has no missing values → `loadtxt` is the natural stdlib-free CSV baseline. | Fact |
| N8 | RNG reproducibility | `default_rng(seed)` is deterministic for a given NumPy version, but `Generator` has **"No Compatibility Guarantee"**: the bit stream may change in newer versions. | <https://numpy.org/doc/stable/reference/random/generator.html> | A fixed seed alone does not guarantee identical data across NumPy versions → record NumPy version **and a content checksum** of the generated dataset in every run. | Fact → Rec |

## 2. Timing and statistics

| # | Claim / question | Finding | Source | Why it matters | Type |
|---|---|---|---|---|---|
| T1 | `perf_counter_ns` semantics | Highest-resolution clock for short durations; includes sleep; same clock across processes; reference point undefined so **only differences are valid**; on CPython monotonic. | <https://docs.python.org/3/library/time.html#time.perf_counter_ns> | Use it for elapsed time (integer ns, no float rounding); never log absolute values. | Fact |
| T2 | `process_time` | CPU time (user+sys) of the process, excludes sleep. | same | Cheap extra metric that exposes decompression/parsing CPU vs I/O wait. | Fact |
| T3 | Mean vs median | pyperf reports mean ± std by default but offers median and MAD as "robust statistics which ignore outliers" when results are unstable. | <https://pyperf.readthedocs.io/en/latest/analyze.html> | Supports median (+ IQR/min/max) as headline for noisy laptop measurements. | Fact → Rec |
| T4 | Outliers | On untuned systems a few runs are much slower; remedy: more runs/values, system tuning, inspect distribution. | same | Never silently drop outliers; keep raw trials. | Fact → Rec |
| T5 | System noise | pyperf documents CPU isolation (`isolcpus`), governor/Turbo settings, plugging in laptops, `pyperf system tune`. Validation: results on an idle vs loaded system must be close. | <https://pyperf.readthedocs.io/en/latest/system.html> | Many controls need root/boot parameters; the MVP **records** governor/load rather than changing the system. | Fact → Rec |
| T6 | Process isolation | pyperf runs benchmarks in worker processes. | <https://pyperf.readthedocs.io/en/latest/system.html> (mentions worker processes; rationale not read in depth, see gap 8) | Motivates one fresh subprocess per trial. The project does **not** depend on pyperf (it targets micro-benchmarks and loops, not file loading). | Rec |

## 3. Memory measurement

| # | Claim / question | Finding | Source | Why it matters | Type |
|---|---|---|---|---|---|
| M1 | Peak RSS in stdlib | `resource.getrusage(RUSAGE_SELF).ru_maxrss` = maximum resident set size of the process. | <https://docs.python.org/3/library/resource.html#resource.getrusage> | No `psutil` needed for a peak-memory metric on Linux. | Fact |
| M2 | Units | Linux: **KiB** ("maximum resident set size used (in KiB)"). (macOS reports bytes; not confirmed in the fetched pages — the man page states KiB for Linux only.) | <https://man7.org/linux/man-pages/man2/getrusage.2.html> | Metric is documented as Linux-specific; unit normalised in code. | Fact |
| M3 | Children | `RUSAGE_CHILDREN` reports the RSS of the **largest single child**, not the peak of the process tree. | same | Parent must not read its own `ru_maxrss` for a worker; the **worker reports its own** `RUSAGE_SELF` value. | Fact |
| M4 | What the number contains | `ru_maxrss` is a high-water mark since process start, so it includes interpreter + imports. | (derived from definition in M1/M2) | Worker also records RSS after imports, before the operation → report `peak_rss` and `peak_minus_baseline`, both labelled. | Rec |

## 4. Filesystem cache

| # | Claim / question | Finding | Source | Why it matters | Type |
|---|---|---|---|---|---|
| C1 | Dropping the page cache | Writing 1/2/3 to `/proc/sys/vm/drop_caches` frees page cache / slab / both; non-destructive for dirty data; "use outside of a testing or debugging environment is not recommended". Root requirement is not stated on the fetched page. | <https://docs.kernel.org/admin-guide/sysctl/vm.html> | Cold-cache runs are system-wide and privileged → not default. | Fact |
| C2 | Process restart ≠ cache clear | Page cache is kernel state shared across processes. | (kernel semantics; implied by C1) | Docs must call the MVP an **ordinary/warm-cache** benchmark. | Rec |

## 5. Other formats (background / deferred)

| # | Claim / question | Finding | Source | Why it matters | Type |
|---|---|---|---|---|---|
| F1 | Parquet structure | File → row groups → one column chunk per column per row group → pages. Column chunks are contiguous; pages are the unit of encoding/compression. | <https://parquet.apache.org/docs/concepts/> | Layout enables per-column I/O. The fetched page does **not** itself state projection benefits (see gaps). | Fact |
| F2 | HDF5 via h5py | Contiguous by default; chunking required for compression and resizing; gzip (portable, levels 0–9, default 4) and lzf (fast, low–moderate compression); NumPy-style slicing = hyperslab partial reads; compound dtypes supported (no nested compound). Suggested chunk size 10 KiB–1 MiB. | <https://docs.h5py.org/en/stable/high/dataset.html> | Chunk shape and compression are experimental *factors*; defer until baseline works. | Fact → Future |
| F3 | ROOT TTree | Columnar **branches**, filled into buffers (default 32000 B) compressed as **baskets**, grouped in clusters; reading only needed branches is "vividly recommended"; RNTuple is the described experimental successor; RDataFrame recommended for reading trees. | <https://root.cern/manual/trees/> | Shows why column projection matters in HEP; ROOT is out of MVP scope and no ROOT claims are made. | Fact → Future |
| F4 | pandas CSV | `read_csv` engines: `c` (default, fast, robust), `python`, `pyarrow` (experimental, multithreaded; docs say generally fastest on larger workloads but less robust). `float_precision='round_trip'` guarantees exact round-trip; docs' own example shows default/`high` differ by ~5.55e-17. | <https://pandas.pydata.org/docs/user_guide/io.html#io-read-csv-table> | (a) A pandas loader is a realistic extra CSV variant but adds a heavy dependency → optional/deferred. (b) Text float round-trip fidelity is a **real correctness hazard** → exact-equality validation. | Fact → Rec |

## 6. Existing tools (what this project does *not* replace)

| Tool | Role | Relation to this project |
|---|---|---|
| pyperf | Rigorous micro-benchmark harness with system tuning | Borrow methodology (worker processes, robust stats); do not wrap it. |
| ROOT / RDataFrame | HEP I/O and analysis framework | Out of scope; project makes no claims about ROOT performance. |
| pandas, PyArrow, h5py | Mature I/O libraries | Possible later variants; MVP uses NumPy only for loaders. |

---

## Gaps and unverified items

These were **not** confirmed by the fetched primary pages and must not be stated as verified facts in the README:

1. Whether `numpy.loadtxt` uses a C parser / its speed relative to pandas — the reference page gives no implementation or performance data. Treat as measurable, not assumed.
2. Whether `np.load(..., mmap_mode=...)` applies to `.npz` — the page documents it only for single-array files. MVP does not use mmap.
3. Whether `.npz` members are read lazily — page implies access by key but does not state it. Loader always materialises all columns, so behaviour is unaffected.
4. Whether `loadtxt`/`savetxt` text round-trips floats exactly — not stated. **Empirical test required in the correctness phase** (plan: write `%.17g` for float64, validate bit-exact equality).
5. Parquet column-projection benefit and encoding details — fetched concepts page was incomplete; needs the Encodings/Compression pages before any Parquet claim.
6. Whether `drop_caches` requires root — the fetched sysctl page does not say. Do not assert it in docs without a source (use "writing to `/proc/sys/vm/drop_caches` is a system-wide operation").
7. macOS `ru_maxrss` units — not confirmed in fetched pages. The project is Linux-only for memory metrics, so this is moot.
8. pyperf's "worker processes" rationale beyond what is in its system/analysis pages was not read in depth.
9. No benchmark numbers from the literature were collected or are claimed; this project must produce its own and must not state that any format is universally fastest.

## Comparison matrix (documented properties only — not performance claims)

| Property | CSV | `.npy` | `.npz` | `.npz` (compressed) |
|---|---|---|---|---|
| Representation | Text, one row per line | Binary, one array with header | Zip of `.npy` members | Zip with DEFLATE |
| Typed / self-describing | No (types supplied by loader) | Yes (dtype, shape in header) | Yes, per member | Yes, per member |
| Mixed-type table | Natural (columns) | Via structured array | One array per column | One array per column |
| Parse step | Text → numbers | None (raw bytes) | None + zip framing | + DEFLATE decompression |
| Human readable | Yes | No | No | No |
| Compression | None | None | None | DEFLATE |
| Partial/column read | Not in MVP | mmap possible (not in MVP) | By member (not in MVP) | By member (not in MVP) |
| Portability | Universal | NumPy-centric (spec documented) | NumPy-centric | NumPy-centric |
