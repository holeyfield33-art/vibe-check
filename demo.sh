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

# A second, distinct cross-file duplicate (its own contiguous block). The window
# merge collapses each duplicated region to one finding, so this stays separate
# from the process/handle block above -> duplicate_blocks: 2, not a pile of windows.
cat > "$DEMO_DIR/util_a.py" << 'EOF'
def compute_total(values):
    total = 0
    for v in values:
        total += v * v
    return total
EOF

cat > "$DEMO_DIR/util_b.py" << 'EOF'
def compute_total(values):
    total = 0
    for v in values:
        total += v * v
    return total
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
echo "# vibe-check - a zero-dependency scanner for AI-generated code debt"
echo "# one file, stdlib only, offline. point it at any repo."
sleep 1.4
echo

# The money shot: human-readable summary + the triage verdict + a CI exit code,
# all from one command. --fail-on hard makes the exit code the CI gate.
type_cmd "python vibe_check.py ./sample-project --format summary --fail-on hard"
sleep 0.3
status=0
python vibe_check.py ./sample-project --format summary --fail-on hard 2>/dev/null || status=$?
sleep 1.2
echo
type_cmd 'echo "exit code: $?"'
echo "exit code: $status"
sleep 1.5
echo
echo "# DEEP_AUDIT_REQUIRED: a file that doesn't parse, a typosquat (requets),"
echo "# and an import missing from requirements.txt (tensorflow)."
sleep 2.0
echo "# exit 1 = this gates CI. two hard axes decide; everything else is"
echo "# reported as observations with honest caveats, never fake scores."
sleep 2.2
echo
echo "# machine formats when you want them: --format triage | prompt | json, --html"
sleep 2.0
