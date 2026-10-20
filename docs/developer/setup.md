# Developer setup

## The deterministic core: no install required

The trust core is standard-library only and `forge_geom`/`forge_kernel` need
nothing but NumPy. On any machine with Python 3.10+:

```console
$ git clone <repo> && cd forge
$ python3 -m pip install numpy       # the only runtime dependency
$ make test
```

There is no build step, no compiled extension, and no CAD kernel to install.
That is deliberate — see [ADR-0002](../adr/0002-zero-dependency-trust-core.md)
and [ADR-0007](../adr/0007-implicit-backend-first.md).

`make` targets:

| Target | Does |
| --- | --- |
| `make test` | Run all 150 tests |
| `make test-fast` | Skip the golden suite (which measures geometry and takes ~90 s) |
| `make verify` | Run the golden clevis end to end and print the evidence |
| `make export` | Write `build/clevis.stl` |
| `make sweep` | Show incremental-compile behaviour across a parameter sweep |
| `make check` | Lint, type-check and test |
| `make clean` | Remove `build/` and caches |

## Windows with WSL2

The reference workstation is Windows 11 with an RTX 4070 Super, 32 GB RAM and
Docker Desktop on the WSL2 backend. Development happens in a Linux container;
only the Fusion bridge runs natively on Windows.

```powershell
PS> wsl --install -d Ubuntu-22.04          # if not already present
PS> wsl
```

Then inside WSL:

```console
$ sudo apt update && sudo apt install -y python3 python3-pip python3-venv git
$ git clone <repo> && cd forge
$ python3 -m venv .venv && source .venv/bin/activate
$ pip install -e ".[dev]"
$ make test
```

Keep the repository on the **Linux filesystem** (`~/forge`), not under
`/mnt/c/...`. Cross-filesystem I/O through the 9P bridge is roughly an order of
magnitude slower, and the test suite feels it.

## The solver stack, in Docker

The heavy solvers — OpenCascade, Gmsh, CalculiX, Project Chrono — are not
installed on the host. They live in containers, which keeps versions pinned and
keeps AI-generated geometry code away from the host filesystem.

```console
$ docker compose build
$ docker compose up -d
$ docker compose run --rm cad forge verify examples/clevis/clevis.forgeir.json
```

Worker containers run with:

- a non-root user,
- `network_mode: none`,
- a read-only root filesystem with a small writable `tmpfs` scratch,
- CPU, memory, PID and file-size limits,
- no mounted Docker socket and no host home directory.

Those constraints are the security model, not a hardening pass. See
[SECURITY.md](../../SECURITY.md).

## GPU

The RTX 4070 Super is not used by anything today. CalculiX is CPU-only;
OpenCascade is CPU-only. GPU acceleration becomes relevant for the implicit
kernel's field evaluation during large optimisation campaigns, which is in the
backlog and not yet justified by measurement.

## Fusion bridge

The Fusion add-in runs natively on Windows, outside WSL and outside Docker,
because it must load inside Fusion's own Python runtime. It is not yet written.
When it is, it will talk to the local API over `localhost` or consume a signed
reconstruction package, and it will never receive credentials.

## Running the test suite

```console
$ make test                       # everything
$ python3 -m unittest discover -s tests -p "test_units.py" -v
$ python3 -m unittest tests.test_golden.InjectedFaults -v
```

The suite uses `unittest` from the standard library rather than pytest, so it
runs in a minimal container with no test framework installed. pytest works too
if you prefer it.

Rough timings on two cores:

| Suite | Tests | Linux, CPython 3.11 | Windows workspace, CPython 3.10 |
| --- | --- | --- | --- |
| `test_units` | 52 | 0.04 s | 0.12 s |
| `test_expr` | 45 | 0.03 s | 0.09 s |
| `test_kernel` | 24 | 5 s | 6 s |
| `test_golden` | 29 | 90 s | 114 s |

`test_golden` is slow because it measures real geometry, repeatedly, for every
injected fault. That is the cost of testing the thing that matters.

## Adding a feature kind

1. Add a `FeatureSpec` to `forge_ir.features._CATALOGUE` — inputs, parameters,
   and the semantic outputs it publishes.
2. Add a builder to `forge_kernel.implicit_backend.BUILDERS`.
3. Add a golden test with known analytic properties.
4. If the implicit backend cannot represent it, add the spec anyway and let
   `builder_for` raise `UnsupportedFeatureError`. Declaring a gap is correct;
   approximating one silently is not.

## Adding an analytical check

Add a function to `forge_analysis.checks` returning a `CheckResult` with its
formula, its source, and its limitations. The limitations field is not optional
and not decorative — `Evidence` raises if an analytical result arrives without
one.
