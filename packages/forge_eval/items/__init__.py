"""The evaluation's per-kind code, by role and kind (V2-stage4b-0b.md, 2): ``items/<role>/<kind>.py``.

Four roles: ``draw`` (the generator's draw), ``brief`` (the brief's words),
``truth`` (its shape model) and ``grade`` (spec grading). The truth role
never imports the grade role or the solver.
"""
