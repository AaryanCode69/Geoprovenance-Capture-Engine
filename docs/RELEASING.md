# Releasing GeoProvenance and getting a DOI

The local tag `v0.1.0` marks the first release. A DOI cannot be created offline:
Zenodo creates one when it archives a release. This page lists the steps to take once
you decide to make the repository public.

> **Before anything goes public**, confirm that the private files are still ignored:
> `git status --ignored docs` must list `docs/patent/`, `docs/MANUSCRIPT_PLAN.md`,
> `docs/V3_INVALIDATION_PLAN.md`, `docs/Journal/` and `docs/Project_1_Journal_V4.pdf`
> as ignored (`!!`). Also check that the tag does not contain them:
> `git archive v0.1.0 | tar -t | grep -E 'patent|MANUSCRIPT|V3_INVALID|Journal|\.pdf$'`
> must print nothing.

## Option A: GitHub + Zenodo integration (usual route)

1. Sign in to <https://zenodo.org> with your GitHub account. Under
   *Account → GitHub*, switch on `AaryanCode69/Geoprovenance-Capture-Engine`.
2. Make the repository public on GitHub, then push the branch and the tag:
   `git push origin main && git push origin v0.1.0`.
3. On GitHub, open *Releases → Draft a new release* and pick tag `v0.1.0`. Use
   the `0.1.0` section of `CHANGELOG.md` as the release notes, then publish.
4. Zenodo archives the release within a few minutes and mints two DOIs: one for this
   version and a *concept* DOI that always resolves to the latest version. It reads
   the title, authors and licence from `.zenodo.json`.
5. Do step C below.

## Option B: reserve the DOI first

Use this if the DOI must already be inside the tagged files.

1. On Zenodo, choose *New upload*, then *Reserve DOI*. Fill in the metadata from
   `.zenodo.json`. Do not publish yet.
2. Write that DOI into the files listed in step C. Then move the tag onto the new commit:
   `git tag -d v0.1.0`, commit, and run `git tag -a v0.1.0 -m "GeoProvenance 0.1.0"`.
3. Upload `git archive --format=zip --prefix=geoprovenance-0.1.0/ v0.1.0 -o geoprovenance-0.1.0.zip`
   to the draft and publish it. Push the repository and tag when ready.

## C. Put the DOI in place

- `CITATION.cff`: uncomment `doi:` and fill it in.
- `README.md`: uncomment the DOI badge and replace `XXXXXXX`.
- The SoftwareX code-metadata table below: C2 and, if used, C3.

With Option A, these edits come after the tag, so commit them as a follow-up. The
concept DOI stays valid for every later release.

## SoftwareX code-metadata table (ready to fill)

| Nr | Code metadata description | Value |
|---|---|---|
| C1 | Current code version | v0.1.0 |
| C2 | Permanent link to code/repository used for this code version | https://github.com/AaryanCode69/Geoprovenance-Capture-Engine/tree/v0.1.0 (Zenodo DOI: *to be added*) |
| C3 | Permanent link to Reproducible Capsule | *optional; e.g. a Code Ocean capsule running `make test` and `make demo-workflow`* |
| C4 | Legal Code License | GNU General Public License v2.0 or later (GPL-2.0-or-later) |
| C5 | Code versioning system used | git |
| C6 | Software code languages, tools, and services used | Python, SQLite, PyQGIS, PyQt5/PyQt6 |
| C7 | Compilation requirements, operating environments & dependencies | QGIS ≥ 3.28 (tested on 4.2.1); Python standard library only; tests: pytest, jsonschema |
| C8 | If available, link to developer documentation/manual | https://github.com/AaryanCode69/Geoprovenance-Capture-Engine/blob/v0.1.0/README.md |
| C9 | Support email for questions | aaryanupadhyay68@gmail.com |

> **Keep the version strings consistent.** Every in-QGIS measurement in this repository
> (`docs/capture_coverage.md`, README, C7 above) is from **QGIS 4.2.1**. If a manuscript
> reports a run on a different build (for example 4.2.2), record that run and its version
> in the repository too, or the paper and the code it cites will disagree on what was tested.

## Later releases

1. Bump `version=` in `src/geoprovenance/metadata.txt`, plus `version` and `date-released`
   in `CITATION.cff` and `version` / `publication_date` in `.zenodo.json`.
2. Add a section to `CHANGELOG.md`.
3. Run `make test` and the demos, commit, then `git tag -a vX.Y.Z -m "GeoProvenance X.Y.Z"`.
4. Push and publish a GitHub release. Zenodo mints a new version DOI automatically.
