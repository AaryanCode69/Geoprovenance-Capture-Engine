#!/bin/sh
# Run a Python script with a QGIS conda environment's own interpreter.
#   evaluation/qgis.sh gp-q42  script.py [args...]
#   evaluation/qgis.sh gp-q334 script.py [args...]
# Environments are created as described in evaluation/ENVIRONMENT.md.
set -e
env_name="$1"; shift
E="${MAMBA_ROOT_PREFIX:-$HOME/micromamba}/envs/$env_name"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export QT_QPA_PLATFORM=offscreen
unset DISPLAY WAYLAND_DISPLAY  # Qt must not try X11/GLX on a desktop session
export QGIS_PREFIX_PATH="$E"
export PYTHONPATH="$E/share/qgis/python:$E/share/qgis/python/plugins:$ROOT/src:$ROOT"
# `micromamba run` applies the environment's activation scripts, which set
# PROJ_DATA, GDAL_DATA and friends; without them CRS lookups fail.
exec "${MICROMAMBA:-$HOME/.local/bin/micromamba}" run -p "$E" python "$@"
