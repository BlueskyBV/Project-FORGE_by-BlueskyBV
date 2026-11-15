"""The spec's per-kind code, by role and kind (V2-stage4b-0b.md, 2): ``items/<role>/<kind>.py``.

Five roles: ``solve`` (the placement solver), ``views`` (the confirmation
views), ``compare`` (two drafts), ``checks`` (the spec checks) and
``words`` (the sentence template). The checks, compare and views roles may
use the solve role; ``forge_spec`` never imports the planner, the judge or
the evaluation.
"""
