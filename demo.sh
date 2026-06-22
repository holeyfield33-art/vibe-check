#!/usr/bin/env bash
# demo.sh - sets up a sample repo with planted issues and runs vibe-check on it.
# Use this to record an asciinema demo:
#
#   asciinema rec vibe-check-demo.cast -c "bash demo.sh"
#
# Then upload the .cast to asciinema.org and embed the player in your README,
# or convert to a looping GIF with: agg vibe-check-demo.cast demo.gif
set -euo pipefail

# --- build a small repo with deliberate problems --------------------------
DEMO_DIR="$PWD/sample-project"
rm -rf "$DEMO_DIR"
mkdir -p "$DEMO_DIR"

cat > "$DEMO_DIR/requirements.txt" << 'EOF'
requets==2.0.0
flask==3.0.0
EOF

cat > "$DEMO_DIR/api.py" << 'EOF'
# A robust, seamless, game-changer API that will leverage synergy
import tensorflow

def process(data):
    result = []
    for item in data:
        if item > 0:
            result.append(item * 2)
    return result
EOF

cat > "$DEMO_DIR/legacy.py" << 'EOF'
def broken(:
    pass
EOF

cat > "$DEMO_DIR/worker.py" << 'EOF'
def handle(data):
    result = []
    for item in data:
        if item > 0:
            result.append(item * 2)
    return result
EOF

cat > "$DEMO_DIR/README.md" << 'EOF'
# Revolutionary Robust Framework
The most powerful, seamless, cutting-edge, blazing fast, world-class solution.
This game-changer will supercharge your workflow with elegant synergy.
EOF

# --- pacing helper: type a command out, then run it ----------------------
type_cmd() {
  printf '$ '
  for ((i=0; i<${#1}; i++)); do printf '%s' "${1:$i:1}"; sleep 0.03; done
  printf '\n'
  sleep 0.4
}

clear
sleep 0.6
echo "# vibe-check - a zero-dependency code scanner"
echo "# point it at any repo, get one JSON report"
sleep 1.2
echo

type_cmd "python vibe_check.py ./sample-project"
sleep 0.3
python vibe_check.py "$DEMO_DIR"
sleep 2.0
echo
echo "# caught: a syntax error, a typosquat (requets),"
echo "# an undeclared import (tensorflow), a cross-file duplicate,"
echo "# and a README that reads like a press release."
sleep 2.5
