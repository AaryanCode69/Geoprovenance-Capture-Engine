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

.PHONY: help venv test test-storage test-plugin test-capture test-qgis fixtures icon \
        deploy undeploy qgis demo1 demo2 demo3 schema-check clean

help:
	@echo "make test          EVERYTHING that runs without QGIS — the usual one"
	@echo "make test-storage  storage suite only (RULES.md §6.1)"
	@echo "make test-plugin   plugin-layer suite only"
	@echo "make test-capture  capture suite only, minus the QGIS-marked tests"
	@echo "make test-qgis     only the tests that need QGIS + pytest-qgis"
	@echo "make venv          create .venv and install dev dependencies"
	@echo ""
	@echo "make deploy        symlink the plugin into the geoprov-dev QGIS profile"
	@echo "make undeploy      remove that symlink"
	@echo "make qgis          launch QGIS on the geoprov-dev profile"
	@echo ""
	@echo "make fixtures      regenerate the fixtures Person B and C consume (RULES.md §3.4)"
	@echo "make icon          regenerate geoprovenance/icon.png"
	@echo "make schema-check  apply schema.sql to a throwaway database and report"
	@echo "make demo1/2/3     run the Review 1 / Review 2 / Final demo"
	@echo "make clean         remove caches, scratch dirs, and throwaway databases"

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

undeploy:
	$(PY) tools/deploy.py unlink

qgis:
	qgis --profile geoprov-dev

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

clean:
	rm -rf .pytest_cache demos/_scratch
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
