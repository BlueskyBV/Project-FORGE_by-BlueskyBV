# Designing from a sentence

`forge design` runs the whole loop: it reads your brief, derives requirements,
asks about anything it would otherwise have to invent, writes a ForgeIR document,
compiles it, repairs what fails, measures the result and gates it.

What comes out is an ordinary ForgeIR file. Everything in
[your first project](first-project.md) applies to it unchanged — inspect it,
change a parameter, re-verify, export it. Nothing about a document is treated
differently for having been generated, and that is the point of the arrangement.

## Setting up

Python 3.10 or newer, and NumPy. From the repository root:

```console
$ python -m pip install -e .
```

That installs NumPy, puts the packages on the path, and gives you a `forge`
command. Check it before spending anything — this runs entirely offline:

```console
$ forge verify examples/clevis/clevis.forgeir.json
$ python -m unittest discover -s tests -p "test_*.py"
```

The verify exits `2`, which is correct: every gate passes and two assumptions are
unaccepted. If the tests pass, the deterministic half works on your machine.

### The key

Windows PowerShell:

```powershell
PS> $env:ANTHROPIC_API_KEY = "sk-ant-..."     # this shell only
```

Linux, macOS, or WSL:

```console
$ export ANTHROPIC_API_KEY=sk-ant-...
```

Then:

```console
$ forge design "..."
```

There is deliberately no `--api-key` option. A key passed as an argument ends up
in shell history and in `ps` output, and nothing Forge writes — report, run log,
fixture, provenance record — ever contains it.

`--model` names the model; the default is a current Sonnet. If a run comes back
saying the API does not recognise the model, the identifier has been retired —
pass a current one with `--model` rather than assuming the adapter is broken.

### What a run costs

The designer call carries the authoring guide and the document schema, which is
most of the cost: roughly 18,000 input tokens and up to 16,000 output. A complete
run — interpret, requirements, design, and a repair or two — lands in the region
of **five to fifteen cents** at current Sonnet pricing. Every report labels the
figure an estimate, because the local price table drifts and the token counts do
not. What *is* recorded is whether the
provider was remote, because that is the fact that matters afterwards: it says
whether your brief and your design left the machine.

To keep everything local, point at any OpenAI-compatible endpoint:

```console
$ forge design "..." --provider openai \
      --base-url http://localhost:11434/v1 --model qwen2.5-coder:32b
```

## What you can ask for

One part at a time, of any shape a brief can describe. Forge has features for
plates and blocks with rounded or chamfered edges; any flat outline (a lever,
a hook, a cam, an L or a T) and any turned section; spur gears; bars, tubes
and handles bent along a path; springs and coils; transitions from one
section to another; bent and curved plates; hollow and open containers;
counterbored and countersunk holes, slots, bolt circles and patterns.

The more the brief says, the more Forge checks. Every size it states is
measured on the built part. Every hole and slot it places -- "on the
centreline, 18 mm from the end", "one at each end, 22 mm in", "on the corners
of a 56 by 36 rectangle", "equally spaced on a 60 mm bolt circle" -- is checked
where it ends up, not just counted. When the brief's own figures make two
openings run into each other, the run says so and stops, rather than
pretending a design could fix it.

## Expect to be asked

A brief that leaves out something load-bearing does not get a design:

```console
$ forge design "I need a bracket to hold a shaft. Make it strong enough."

State     : awaiting_answers

Before this can be designed, these need answering:
  - [UNK_LOAD] What load does the shaft carry, and in what direction?
      why: Nothing can be sized or verified without it.
  - [UNK_SHAFT_DIAMETER] What diameter is the shaft?
      why: Sets the bore and drives every other dimension.
      e.g. 8 mm, 10 mm, 12 mm, 20 mm
```

Exit code `3`. Answer and re-run — the command to do it is printed for you:

```console
$ forge design "I need a bracket to hold a shaft. Make it strong enough." \
    --answer UNK_LOAD="600 N downward, static" \
    --answer UNK_SHAFT_DIAMETER="12 mm"
```

Answers can also live in a file, which is easier to keep and to edit:

```console
$ forge design "..." --answers answers.json     # {"UNK_LOAD": "600 N, static"}
```

### Or proceed without answering

```console
$ forge design "..." --assume
```

This does **not** mean a value gets made up. Each unresolved unknown is recorded
as an unapproved, high-risk assumption saying what is unknown and what it blocks.
The design is still built and still measured — which is often useful — and
release is blocked with the unknown named. You get a real part and an honest
account of what nobody has decided.

## Reading the result

Every run writes a directory:

```
runs/20260912T141903-a-bracket-holding-a-20-mm-shaft/
  run.json               every event, every repair, every token spent
  run.txt                the same, rendered
  document.forgeir.json  the design
  evidence.json          each claim, its method, its limitations
  evidence.txt
  questions.json         only when the run stopped to ask
```

`run.json` is the audit trail. It records the repairs that were *attempted*, not
just the one that worked, including the ones that were abandoned. That is
deliberate: a loop that quietly retries until something works and reports only
the success is how a bad design gets a clean report.

Read the verdict before the gates. A run can pass every gate and still come back
`BLOCKED`, because an assumption nobody accepted is standing behind the numbers.

## Cost, and keeping it down

```console
$ forge design "..." --max-cost 0.50 --max-calls 20
```

Budgets are hard stops checked *before* each call leaves, not warnings after the
fact. A run that would exceed its budget stops and says so.

The cheapest thing you can do is record your first run:

```console
$ forge design "..." --record fixtures/bracket
$ forge design "..." --provider fixture --fixtures fixtures/bracket
```

The replay is free, offline, and byte-identical — useful for re-running a design
after changing something in the kernel, and for keeping a reproducible example of
a run that went interestingly wrong.

## When something goes wrong

| Exit | Meaning | What to do |
| --- | --- | --- |
| 0 | the design passed every gate and is releasable | read `evidence.txt` anyway |
| 1 | the run failed — it could not produce a valid design | `run.json` says at which step |
| 2 | built, measured, and not releasable | usually an unapproved assumption |
| 3 | it stopped to ask | answer and re-run |

A `fixture missing` error while replaying means a prompt changed since the
recording. Re-record; do not loosen the matching. The whole value of a fixture is
that it answers the prompt it was recorded against.

## What it will not do

- Design something it was not asked about clearly enough to verify.
- Invent a load, a material grade, or a safety factor.
- Improve a design that already passes — repair fixes failures, and the
  optimiser is not written yet.
- Drive more than one component. The document model carries several; the loop
  compiles the first.
