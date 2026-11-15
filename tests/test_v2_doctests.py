"""The examples in V2's docstrings are tests too, so they can't go stale.

Run as one test per module under any runner (pytest doesn't follow
unittest's ``load_tests``), each failing with the examples that went wrong.
"""

from __future__ import annotations

import doctest
import importlib
import io
import pkgutil
import unittest

import forge_checks
import forge_eval
import forge_spec

#: Every module of V2's packages: one added later is tested without being listed.
MODULES = tuple(
    f"{package.__name__}.{module.name}"
    for package in (forge_spec, forge_eval, forge_checks)
    for module in pkgutil.iter_modules(package.__path__)
)


class TheExamplesInTheDocstringsHold(unittest.TestCase):
    def test_every_module(self) -> None:
        tried = 0
        for name in MODULES:
            module = importlib.import_module(name)
            out = io.StringIO()
            runner = doctest.DocTestRunner(optionflags=doctest.ELLIPSIS)
            for test in doctest.DocTestFinder().find(module):
                runner.run(test, out=out.write)
            result = runner.summarize(verbose=False)
            tried += result.attempted
            with self.subTest(module=name):
                self.assertEqual(result.failed, 0, out.getvalue())
        self.assertGreater(tried, 60)  # 82 when written


if __name__ == "__main__":
    unittest.main()
