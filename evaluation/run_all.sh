#!/bin/sh
# Re-run every measurement in the manuscript's evaluation, then regenerate its
# tables, numbers and figures. One command; about two hours on the E8 machine.
# Needs the three micromamba environments of evaluation/ENVIRONMENT.md.
#
#   evaluation/run_all.sh            everything
#   evaluation/run_all.sh report     only the tables and figures, from existing results
set -e
cd "$(dirname "$0")/.."
Q=evaluation/qgis.sh
GRASS_PATH="$HOME/micromamba/envs/gp-grass/bin"
step() { echo "== $(date +%H:%M:%S) $*"; }

if [ "$1" != "report" ]; then
  step "E8 hardware";            python3 evaluation/hardware.py
  step "unit tests (no QGIS)";   .venv/bin/python -m pytest tests -q -m "not qgis" -p no:pytest_qgis \
                                   --junitxml=evaluation/tests_noqgis.xml > evaluation/tests_noqgis.txt 2>&1
  step "E1 perturbation suite";  $Q gp-q42 evaluation/perturb_suite/run_suite.py > evaluation/perturb_suite/results/final_run.log 2>&1
  step "E2 baselines";           $Q gp-q42 evaluation/baselines/run_baselines.py > /dev/null 2>&1
  step "case study 1";           $Q gp-q42 evaluation/case_cuddalore/run_in_qgis.py baseline > /dev/null 2>&1
                                 $Q gp-q42 evaluation/case_cuddalore/run_in_qgis.py perturb > /dev/null 2>&1
  step "case study 2";           PATH="$GRASS_PATH:$PATH" $Q gp-q42 evaluation/case_hydro/run_in_qgis.py > /dev/null 2>&1
  step "E6 audit";               rm -f evaluation/audit/results/scenarios.json
                                 .venv/bin/python evaluation/audit/scenarios.py offline > /dev/null
                                 $Q gp-q334 evaluation/audit/scenarios.py q334 > /dev/null 2>&1
  for env in gp-q42 gp-q334; do
    step "E7 completeness $env"; $Q $env evaluation/completeness/run_paths.py > /dev/null 2>&1
    step "QGIS tests $env";      $Q $env -m pytest tests -q -m qgis -p no:cacheprovider \
                                   --junitxml=evaluation/tests_${env#gp-}.xml > evaluation/tests_${env#gp-}.txt 2>&1 || true
    step "E3 overhead $env";     $Q $env evaluation/overhead/run_overhead.py > /dev/null 2>&1
  done
  step "Fig. 4 panel";           $Q gp-q42 evaluation/figures/panel_shot.py > /dev/null 2>&1
  step "E3 fingerprint cost";    $Q gp-q42 evaluation/overhead/fingerprint_bench.py generate > /dev/null 2>&1
                                 $Q gp-q42 evaluation/overhead/fingerprint_bench.py measure > /dev/null 2>&1
fi
step "report";                   "$HOME/.local/bin/micromamba" run -p "$HOME/micromamba/envs/gp-q42" python evaluation/report.py
step "diagrams"
npx -y @mermaid-js/mermaid-cli@12.0.0 -q -p docs/Journal/array/figures/puppeteer.json \
    -i docs/Journal/array/figures/fig2_architecture.mmd -o docs/Journal/array/figures/fig2_architecture.png -s 2 -b white
for f in fig_coastal_workflow fig_hydro_tree fig3_verdict_order; do
  dot -Tpng -Gdpi=300 docs/Journal/array/figures/$f.dot | magick - -alpha remove -alpha off docs/Journal/array/figures/$f.png
done
step "done"
