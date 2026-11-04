#!/bin/sh
# Runs python in the heightmaps python image (numpy, scipy, pillow) with this worktree at /vol, the heightmaps
# tools at /hm and ~/data at /data. Heavy jobs: prefix with `nice -n 10`.
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
exec docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e PYTHONPATH=/vol/tools/volumetric/py:/vol/tools/volumetric/semantics:/hm \
  -v "$ROOT:/vol" -v "$ROOT/tools/heightmaps/py:/hm:ro" -v "$HOME/data:/data" -w /vol/tools/volumetric/semantics squadcalc-heightmaps-py python -W ignore "$@"
