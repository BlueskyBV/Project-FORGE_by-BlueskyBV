"""forge_eval - measuring Forge honestly.

Answer keys written before Forge runs, graders, and the confidence bounds every
reported rate carries (plan, section 7). Nothing here is used to build a part;
it only measures how well parts are built.

Built so far: :mod:`~forge_eval.bounds` (confidence bounds),
:mod:`~forge_eval.keys` (locked answer keys), :mod:`~forge_eval.spec_grade`
(grading a drafted spec before anything is built, stage 1), and
:mod:`~forge_eval.generator` with :mod:`~forge_eval.truth` (random parts with
the definitions' own answer for every copy and solid, stage 2).
"""

from __future__ import annotations

from .bounds import binomial_cdf, trials_needed, upper_bound

__all__ = ["binomial_cdf", "trials_needed", "upper_bound"]
