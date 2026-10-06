# Contributing to GeoProvenance

Thank you for your interest. Bug reports, questions and pull requests are welcome.

## Reporting a problem

Open an issue at
<https://github.com/AaryanCode69/Geoprovenance-Capture-Engine/issues> and include:

- your QGIS version, operating system, and the Python version QGIS reports
  (in the QGIS Python console: `import sys; sys.version`);
- what you did, what you expected, and what happened;
- anything in the **GeoProvenance** tab of *View → Panels → Log Messages*.

For anything you would rather not post publicly, email aaryanupadhyay68@gmail.com.

## Making a change

```bash
make venv     # create .venv with the development dependencies
make test     # everything that runs without QGIS; must pass before a pull request
```

Tests that need a running QGIS run inside QGIS with `make test-qgis`. Do not run
`pytest tests` directly: see [`docs/DEVELOPMENT.md`](./docs/DEVELOPMENT.md).

Ground rules:

- **No third-party dependencies in plugin code.** `src/geoprovenance/` uses only the
  Python standard library and PyQGIS/PyQt. Raise an issue first if you think a
  dependency is unavoidable.
- **Capture must never break the user's QGIS run.** Code that runs inside a Processing
  execution catches and logs its own failures.
- **Storage, fingerprinting, PROV, audit and layout code import no QGIS.** A guard test
  (`tests/storage/test_no_qgis_imports.py`) enforces this.
- Add or update tests together with the code they cover.
- Changes to the database shape (`src/geoprovenance/storage/schema.sql`) need a migration
  in `storage/migrations.py` and a test in `tests/storage/test_migrations.py`.

By contributing you agree that your contribution is licensed under the project's
licence, GPL-2.0-or-later.
