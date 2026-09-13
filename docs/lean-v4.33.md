# Lean 4.33 workspace

This branch runs Kimina at `http://127.0.0.1:8033`, independently of the Lean 4.15
server on port 8000. The checkout is `~/kimina-lean-server-v4.33`, branch
`lean-v4.33`. Its Python environment is `.venv/`.

## Pinned components

| Component | Revision |
| --- | --- |
| Lean | `leanprover/lean4:v4.33.0` (`d8b18978322de05a8f3dba51ef03cf5461676c17`) |
| Mathlib | `db584cd6d46c92f209a44c0f1c829460d327499d` (`v4.33.0`) |
| Custom REPL base | `VSumanth99/repl`, `b360a8604b7736140aa3940e83d5f9dc4f88de98` |
| AST exporter base | `KellyJDavis/ast_export`, `4b7d6d7442effd104f300dd1eac6fbedd907dc67` |

The dependency source changes are stored in
[`repl-v4.33.patch`](../patches/repl-v4.33.patch) and
[`ast_export-v4.33.patch`](../patches/ast_export-v4.33.patch). The nested checkouts
also use local `lean-v4.33` branches (`c1a1a7a` for the REPL and `98729aa` for
the exporter). Mathlib's committed manifest pins its
transitive dependencies; the exporter shares those same checkouts and artifacts.

The Linux Lean release archive was checked against its published SHA-256:
`4b3fb03c29a1e0a253fb1d11f9bae3725f19a0dc6fc09b3ea16d2c9df3349e2c`.
The toolchain is installed in Elan's standard toolchain directory.

## Recreate dependencies in a fresh checkout of this branch

Use these commands for this profile. The generic `setup.sh` expects matching
remote version branches, which do not contain these local compatibility patches.

```bash
uv sync --frozen --extra server
source .venv/bin/activate
.venv/bin/python -m prisma generate --schema server/prisma/schema.prisma
elan toolchain install leanprover/lean4:v4.33.0

git clone --depth 1 --branch v4.33.0 https://github.com/leanprover-community/mathlib4.git mathlib4
git -C mathlib4 checkout db584cd6d46c92f209a44c0f1c829460d327499d

git init repl
git -C repl remote add origin https://github.com/VSumanth99/repl.git
git -C repl fetch --depth 1 origin b360a8604b7736140aa3940e83d5f9dc4f88de98
git -C repl checkout -b lean-v4.33 FETCH_HEAD
git -C repl apply ../patches/repl-v4.33.patch

git init ast_export
git -C ast_export remote add origin https://github.com/KellyJDavis/ast_export.git
git -C ast_export fetch --depth 1 origin 4b7d6d7442effd104f300dd1eac6fbedd907dc67
git -C ast_export checkout -b lean-v4.33 FETCH_HEAD
git -C ast_export apply ../patches/ast_export-v4.33.patch

(cd mathlib4 && lake exe cache get)
(cd repl && lake build)
(cd ast_export && lake build)
cp .env.template .env
```

## Start and stop

Activate this checkout's environment so that subprocesses use its Python tools:

```bash
cd ~/kimina-lean-server-v4.33
source .venv/bin/activate
.venv/bin/python -m server
```

The configured worker limit is four REPLs and two AST jobs. Each REPL has a
16 GiB virtual-address-space limit: a Mathlib import measured approximately
12.5 GiB virtual memory and 3.2 GiB resident memory, exceeding the old 8 GiB limit.

The instance started during setup runs in the background. Its PID is in
`server.pid` and logs are in `server.log`. Stop that instance with
`kill "$(cat server.pid)"` from this checkout before starting another on 8033.
For the informalization pipeline, set `kimina_url=http://127.0.0.1:8033`.

## Compatibility changes

- Updated removed/renamed Lean imports, source-position types, info-tree variants,
  and command elaboration syntax while preserving the existing JSON shapes.
- Kept source positions as UTF-8 byte offsets, including local notation and term proofs.
- Flattened Lean 4.33's anonymous trace containers while retaining named trace children.
- Preserved `declaration uses 'sorry'` in warning messages: existing clients match
  that wording when rejecting incomplete proofs. Structured `sorries` remain present.
- Recognized module headers and public/meta imports when preparing reusable REPLs.
- Created output directories for nested module AST exports.
- Preserved leading comments in `header.info.leading`, including files without
  imports, using Lean's parser and UTF-8 byte offsets.
- Added each calc step's checked `target` to `calcBlocks`, so clients can read
  resolved relations without requesting the full info tree.

## Validation

The integration tests cover proof checking, proof-state certificate acceptance and
rejection, info trees, nested tactic sequences, calc blocks, automation traces,
ASTs for source and modules, Unicode offsets, local notation, module-header reuse,
and term/tactic placeholders. Run them with:

```bash
source .venv/bin/activate
.venv/bin/pytest
.venv/bin/pre-commit run --all-files
```

The existing informalization `LeanVerifier` and `HierarchyBuilder` were exercised
against port 8033 using a separate test cache. Erdős 1077 from the local corpus
passed checking (73 tactic sequences, 6 calc blocks), AST export (27 commands), and
the final theorem's axiom audit (`propext`, `Classical.choice`, `Quot.sound`).
Erdős 106 exceeded a 120-second limit for both checking and AST export; it has not
been validated under a longer timeout. No corpus-wide compatibility claim is made.

The server suite passed **70 tests**, with two existing explicit skips and 103
performance/compatibility tests deselected by the default marker expression.
Ruff and mypy passed. The full Pyright hook still reports existing errors in
`server/prisma_client.py` and `server/routers/proof_step.py`; neither file was changed.

The pipeline's existing hierarchy cache does not include the Lean environment in
its key. Use a separate pipeline checkout/cache for each environment until that
pipeline change is implemented.
