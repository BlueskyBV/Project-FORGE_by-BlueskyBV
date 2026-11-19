# Your first part with V2

V2 splits a run in two. First a model drafts the part's spec, you settle
what only you can, and you confirm it. Then Forge builds the confirmed spec
with no model at all, judges the part on every view, and releases its files
only when everything agrees. This page walks through one part. The design
behind it is in [V2-plan.md](../V2-plan.md); `forge build` is section 9 of
[V2-stage4.md](../V2-stage4.md).

## 1. Check the exact kernel works here

```console
$ forge doctor
ok    python  Python 3.14.10
ok    pins    OpenCascade 8.0.1 (cadquery-ocp-novtk 8.0.1.1.0), lib3mf 2.5.0
ok    probe   probe built in 4 steps, every one after-checked; 14021.493 mm³ as worked out; its faces named
ok    step    STEP written (50,425 bytes) and read back: within 1.5e-09 of the part
ok    meshes  STL and 3MF written and read back: 1,416 triangles, within 0.0030 mm of the surface (tolerance 0.01 mm)
all checks passed
```

It needs no key and no network. Exit code 0 means every check passed.

## 2. Draft the spec, and confirm it

`forge spec` is the one step that calls a model, so it needs your key in
the environment, for that window only. In PowerShell:

```console
PS> $env:ANTHROPIC_API_KEY = "<your key>"
PS> forge spec "a 40 x 30 x 5 mm plate with a 6 mm hole through its middle"
```

What happens, in order:

1. Forge numbers every word of the brief, and the spec writer drafts the
   spec. Every value in it cites the words it came from, and every number
   and sentence of the brief must be accounted for.
2. You read the spec in fixed wording, and `spec.html` in the run's folder
   shows it with the brief coloured by what each word became, and the part
   in 3D.
3. You answer one round of questions and assumptions, each by choosing an
   option. Forge applies the answers itself; it never asks the model to.
4. When nothing is left to settle, Forge shows a short code in its own
   window and you type it back. Only then is the spec locked, and sealed
   with this installation's key (kept in `~/.forge`).

The run's folder (`runs/spec-<time>-<brief>`) then holds `confirmed.json`.
Exit codes: 0 locked; 1 refused (the writer couldn't clear its faults, or the
part can't be made); 2 you stopped, or an error; 3 questions an automatic
run can't answer.

With `--auto` no person takes part: the stricter checks apply, nothing is
asked, and a draft with nothing left to settle is locked as a draft. A part
built from it can end BUILT TO DRAFT at best, never VERIFIED.

## 3. Build it

```console
$ forge build runs/spec-<time>-<brief>
```

No model is called from here on. For the plate above, confirmed by a person
(its spec named `plate`), it prints:

```
Spec     : 'plate', 2 item(s), digest 99f13010eba7…, confirmed by a person, sealed
Build    : runs/spec-<time>-<brief>/build
Judge    : 8 checks, coverage radius 0.5 mm
Plan     : 2 item(s), 1 build(s), 0 refusal(s)
B-rep    : 8 of 8 checks, face accounting (38,612 points), topology, volume, fresh probes: passed
Second kernel: 71,314 points compared: agrees
plate.step: 8 of 8 checks, face accounting (38,692 points), topology, volume, fresh probes: passed
plate.stl: 8 of 8 checks, face accounting (21,650 points), topology, volume, fresh probes: passed
plate.3mf: 8 of 8 checks, face accounting (21,650 points), topology, volume, fresh probes: passed
VERIFIED: every check passed on every view; released plate.step, plate.stl, plate.3mf
```

Each line is one judge of the part:

- **B-rep** is OpenCascade's exact model.
- **Second kernel** is V1's implicit kernel, built from the same document.
- **The STEP, STL and 3MF lines** are the files themselves, written, read
  back and judged again. The meshes are judged by Forge's own code, not
  OpenCascade's.

On every view the same things are checked: every size and place of every
item, **face accounting** (every built surface is one the spec asks for,
and every surface it asks for is built), the count of solids and voids, the
volume, and **fresh probes** drawn from a new seed for each build.

The build goes into a folder of its own, never over an earlier build:

```
runs/spec-…/build/
  plate.step  plate.stl  plate.3mf   the files, released only when the ending allows
  verdict.md  verdict.json           the ending and the evidence, written last
  record/                            the document built, the build and the judge, in full
```

## 4. The endings

| Ending | Exit | Means | What you can do |
|---|---|---|---|
| **VERIFIED** | 0 | Matches the spec you confirmed: every item checked on every view | Print it |
| **VERIFIED EXCEPT** | 0 | As above, except what `verdict.md` lists under "Not checked" | Look at those items |
| **BUILT TO DRAFT** | 0 | Every check passed, against a spec nobody confirmed (`--auto`) | Confirm the spec, and build it again |
| **HELD** | 1 | A check failed, or two views disagree; "What holds it" says which, with the numbers | Read it; edit the spec, or report it as a Forge bug |
| **UNABLE** | 3 | Forge couldn't build an item it should: "The gap" names it | Report it; describe the item differently |
| **CAN'T** | 4 | The spec can't be made, with the reason | Edit the spec |

Exit code 2 is a refused command line or confirmed spec, or an error of
Forge's own. Files are released beside the verdict only for the first three
endings. For the others they are kept in `record/files`.

## 5. Reading `verdict.md`

- **Items:** each item, its kind, how it is checked (*exact* where its whole
  surface is known; *bounded* where it lies between known limits, as at a
  rounding's corner), and whether everything of it passed on each view.
- **Not checked:** fields of the spec no check holds; their presence makes
  the ending VERIFIED EXCEPT.
- **Not cross-checked:** what one judge doesn't count but others do (for
  now, the oracle doesn't count through holes in the topology). These change
  no ending.
- **The surface:** how much of the built surface was checked exactly and
  how much within bounds, and the coverage radius (every point of the
  surface is within it of a checked point).
- **Files:** each file's size and SHA-256, so the file you print can be
  matched to the one that was judged.
- **Time:** each stage's seconds.

`forge build --seed <n>` draws the fresh probes from a seed you choose (by
default a new one, recorded in the verdict), and `--formats step,stl`
makes only the files you name.
