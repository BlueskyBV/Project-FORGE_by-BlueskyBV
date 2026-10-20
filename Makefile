# Forge - development tasks
#
# The deterministic core has no third-party test dependency, so `make test`
# works in a minimal container with nothing installed but NumPy.

PKG := packages
PYTHONPATH := $(PKG)
export PYTHONPATH

PYTHON  ?= python3
EXAMPLE := examples/clevis/clevis.forgeir.json
BUILD   := build

.PHONY: help test test-fast test-ai design verify export sweep inspect capability check lint types clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

test:  ## Run every test (about 50 minutes)
	$(PYTHON) -m unittest discover -s tests -p "test_*.py"

test-fast:  ## Skip the suites that measure real geometry
	$(PYTHON) -m unittest discover -s tests -p "test_units.py"
	$(PYTHON) -m unittest discover -s tests -p "test_expr.py"
	$(PYTHON) -m unittest discover -s tests -p "test_kernel.py"
	$(PYTHON) -m unittest discover -s tests -p "test_patch.py"
	$(PYTHON) -m unittest discover -s tests -p "test_models.py"

test-ai:  ## The design loop, replayed from fixtures (no key, no network)
	$(PYTHON) -m unittest discover -s tests -p "test_orchestrator.py"
	$(PYTHON) -m unittest discover -s tests -p "test_cli_design.py"

design:  ## Run the design loop. Needs ANTHROPIC_API_KEY in the environment.
	@# BRIEF="..." make design
	@test -n "$(BRIEF)" || { echo 'usage: BRIEF="a 20 mm shaft bracket..." make design'; exit 2; }
	$(PYTHON) -m forge_cli design "$(BRIEF)" -v

verify:  ## Verify the golden clevis end to end
	@# Exit code 2 is expected here and is the point of the example: every gate
	@# passes, and the design is still BLOCKED because its load and material are
	@# assumptions nobody has accepted. The `||` keeps make from stopping.
	@$(PYTHON) -m forge_cli verify $(EXAMPLE) \
	  --load 500N --arm 35mm --load-assumption ASM_DESIGN_LOAD \
	  || echo "\n(exit 2 = undecided. Accept the assumptions and this returns PASS.)"

inspect:  ## Show parameters, feature graph and published geometry
	$(PYTHON) -m forge_cli inspect $(EXAMPLE)

export:  ## Write build/clevis.stl
	@mkdir -p $(BUILD)
	$(PYTHON) -m forge_cli export $(EXAMPLE) -o $(BUILD)/clevis.stl --resolution 160

sweep:  ## Show what the incremental compiler avoids
	$(PYTHON) -m forge_cli sweep $(EXAMPLE) \
	  --parameter root_blend --start 1mm --stop 5mm --steps 9

capability:  ## Print the truthful capability matrix
	$(PYTHON) -m forge_cli capability

lint:  ## ruff, if installed
	@command -v ruff >/dev/null && ruff check $(PKG) tests || \
	  echo "ruff not installed; skipping (pip install -e '.[dev]')"

types:  ## mypy, if installed
	@command -v mypy >/dev/null && mypy $(PKG) || \
	  echo "mypy not installed; skipping (pip install -e '.[dev]')"

check: lint types test  ## Everything

clean:
	rm -rf $(BUILD)
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete
