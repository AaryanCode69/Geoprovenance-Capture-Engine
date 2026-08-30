# GeoProvenance — Person A
#
# One command per job. `make help` lists them.
#
# Why the storage suite needs -p no:pytest_qgis:
#   pytest-qgis registers a pytest11 entrypoint that does `from qgis.core import ...`
#   at PLUGIN LOAD time, before any conftest runs. On a machine without QGIS that
#   crashes pytest during startup, so `pytest tests/storage` fails even though the
#   storage suite itself imports zero QGIS. Disabling the plugin restores the
#   guarantee in RULES.md §6.1: the storage suite runs anywhere.

PY := .venv/bin/python

# How to run a script inside QGIS's own Python.
#
# QGIS on this machine is the Flathub build, which is sandboxed: its Python
# cannot see the repository unless told to, and PyQGIS is not on its path by
# default (qgis lives in /app/share/qgis/python, the processing plugin one
# directory further down). QGIS_PREFIX_PATH must point at /app, not /usr.
#
# Override the whole thing for a native install:
#     make qgis-demo-project QGIS_PY=python3
QGIS_APP    := org.qgis.qgis
QGIS_PYPATH := /app/share/qgis/python:/app/share/qgis/python/plugins:$(CURDIR)
QGIS_PY     ?= flatpak run --command=python3 --filesystem=home \
                 --env=PYTHONPATH=$(QGIS_PYPATH) \
                 --env=QGIS_PREFIX_PATH=/app \
                 --env=QT_QPA_PLATFORM=offscreen $(QGIS_APP)

.PHONY: help venv test test-storage test-prov test-fingerprint test-audit test-layout \
        test-plugin test-capture test-qgis fixtures icon demo-workflow \
        deploy undeploy where qgis demo1 demo2 demo3 schema-check clean \
        qgis-demo qgis-demo-inputs qgis-demo-record qgis-demo-run qgis-demo-layers \
        qgis-demo-project qgis-demo-verify qgis-demo-open qgis-demo-clean

help:
	@echo "make test          EVERYTHING that runs without QGIS — the usual one"
	@echo "make test-storage  storage suite only (RULES.md §6.1)"
	@echo "make test-prov     Person B's PROV layer only    — no QGIS needed"
	@echo "make test-fingerprint  Person B's fingerprint layer — no QGIS needed"
	@echo "make test-audit    Person C's audit scorer only  — no QGIS needed"
	@echo "make test-layout   Person C's family-tree layout — no QGIS needed"
	@echo "make test-plugin   plugin-layer suite only"
	@echo "make test-capture  capture suite only, minus the QGIS-marked tests"
	@echo "make test-qgis     only the tests that need QGIS + pytest-qgis"
	@echo "make venv          create .venv and install dev dependencies"
	@echo ""
	@echo "make deploy        symlink the plugin into the geoprov-dev QGIS profile"
	@echo "make undeploy      remove that symlink (from every profile root)"
	@echo "make where         which QGIS profile root will be used, and why"
	@echo "make qgis          launch QGIS on the geoprov-dev profile"
	@echo ""
	@echo "make fixtures      regenerate the fixtures Person B and C consume (RULES.md §3.4)"
	@echo "make icon          regenerate geoprovenance/icon.png"
	@echo "make schema-check  apply schema.sql to a throwaway database and report"
	@echo "make demo1/2/3     run the Review 1 / Review 2 / Final demo"
	@echo "make demo-workflow the family tree + score demo (no QGIS needed)"
	@echo "make clean         remove caches, scratch dirs, and throwaway databases"
	@echo ""
	@echo "make qgis-demo         build the whole visual demo, end to end"
	@echo "  qgis-demo-inputs     write the three starting datasets       (no QGIS)"
	@echo "  qgis-demo-run        run the four steps inside QGIS          (needs QGIS)"
	@echo "  qgis-demo-record     record the same four steps offline      (no QGIS)"
	@echo "  qgis-demo-layers     turn the record into map layers         (no QGIS)"
	@echo "  qgis-demo-project    style them into a QGIS project          (needs QGIS)"
	@echo "  qgis-demo-verify     reopen the project and check every layer (needs QGIS)"
	@echo "make qgis-demo-open    open the finished project in QGIS"

venv:
	python3 -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements-dev.txt
	@echo
	@echo "RULES.md §2.1 — confirm this matches your QGIS's Python:"
	@$(PY) -c "import sys; print('  venv Python:', sys.version.split()[0])"
	@echo "  In the QGIS Python console run:  import sys; sys.version"

# Everything that does not need a QGIS process. This is the suite that gets run
# constantly, so as much as possible is kept runnable here (RULES.md §6.1).
test:
	$(PY) -m pytest tests -q -m "not qgis" -p no:pytest_qgis

test-storage:
	$(PY) -m pytest tests/storage -q -p no:pytest_qgis

# Person B's PROV layer and Person C's scorer and layout. Same promise as the
# storage suite: no QGIS, runs anywhere (RULES.md §6.1).
test-prov:
	$(PY) -m pytest tests/prov -q -p no:pytest_qgis

test-fingerprint:
	$(PY) -m pytest tests/fingerprint -q -p no:pytest_qgis

test-audit:
	$(PY) -m pytest tests/audit -q -p no:pytest_qgis

test-layout:
	$(PY) -m pytest tests/ui -q -p no:pytest_qgis

test-plugin:
	$(PY) -m pytest tests/plugin -q -p no:pytest_qgis

test-capture:
	$(PY) -m pytest tests/capture -q -m "not qgis" -p no:pytest_qgis

# Needs QGIS + pytest-qgis. Run inside the geoprov-dev profile.
test-qgis:
	$(PY) -m pytest tests -q -m qgis

fixtures:
	$(PY) tests/fixtures/build_fixtures.py

icon:
	$(PY) tools/make_icon.py

deploy:
	$(PY) tools/deploy.py link

# The first thing to run when QGIS shows no plugin. QGIS keeps its profiles
# under a directory named for its MAJOR version, so a QGIS 3 machine and a
# QGIS 4 machine deploy to different trees (docs/capture_coverage.md §4,
# 26 Aug 2026 — getting this wrong fails silently).
where:
	$(PY) tools/deploy.py where

undeploy:
	$(PY) tools/deploy.py unlink

# The desktop application, on the development profile (RULES.md §2.4).
qgis:
	flatpak run $(QGIS_APP) --profile geoprov-dev

schema-check:
	@$(PY) -c "import sqlite3,pathlib,tempfile,os; \
sql=pathlib.Path('geoprovenance/storage/schema.sql').read_text(); \
p=os.path.join(tempfile.mkdtemp(),'t.db'); c=sqlite3.connect(p); c.executescript(sql); \
t=[r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\")]; \
i=[r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx%'\")]; \
print('schema OK  user_version=%d  tables=%d  indices=%d' % (c.execute('PRAGMA user_version').fetchone()[0], len(t), len(i)))"

demo1:
	$(PY) demos/review1.py

demo2:
	$(PY) demos/review2.py

demo3:
	$(PY) demos/final.py

# Capture -> family tree -> score, end to end, with no QGIS anywhere.
demo-workflow:
	$(PY) demos/workflow.py

clean:
	rm -rf .pytest_cache demos/_scratch
	find . -name __pycache__ -type d -prune -exec rm -rf {} +


# ---------------------------------------------------------------------------
# The visual demo (qgis_demo/)
#
# Two of these steps need QGIS and three do not, which is deliberate: the parts
# that decide what goes where run anywhere, and only the styling needs QGIS.
# ---------------------------------------------------------------------------

# These steps feed each other: the record cannot be drawn before it exists, and
# the project cannot be styled before the layers are written. If make is run
# with -j (or MAKEFLAGS carries it from the environment) they would otherwise
# start together and fail in a confusing order.
.NOTPARALLEL:

qgis-demo: qgis-demo-inputs qgis-demo-run qgis-demo-layers qgis-demo-project qgis-demo-verify
	@echo
	@echo "Done. Open it with:  make qgis-demo-open"

qgis-demo-inputs:
	$(PY) -m qgis_demo.make_inputs

# Runs the four steps in a real QGIS, so the outputs on disk are ones QGIS
# actually produced and the record is one the capture code actually made.
qgis-demo-run:
	$(QGIS_PY) qgis_demo/run_in_qgis.py

# The same four steps with no QGIS anywhere, for a machine that has none
# (RULES.md §7.3). Writes the record but not the output files.
qgis-demo-record:
	$(PY) -m qgis_demo.replay

qgis-demo-layers:
	$(PY) -m qgis_demo.export_layers

qgis-demo-project:
	$(QGIS_PY) qgis_demo/build_project.py

qgis-demo-verify:
	$(QGIS_PY) qgis_demo/verify_project.py

qgis-demo-open:
	flatpak run $(QGIS_APP) --profile geoprov-dev qgis_demo/project/GeoProvenance.qgz

qgis-demo-clean:
	rm -rf qgis_demo/project qgis_demo/data/derived qgis_demo/_hooks \
	       qgis_demo/provenance.db qgis_demo/provenance.db-wal \
	       qgis_demo/provenance.db-shm qgis_demo/findings.txt
