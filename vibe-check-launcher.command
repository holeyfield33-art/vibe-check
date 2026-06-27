#!/usr/bin/env bash
cd "$(dirname "$0")"
clear
echo "===================================================="
echo " vibe-check: Zero-Dependency Code Quality Scanner"
echo "===================================================="
echo ""
read -p "Drag and drop your project directory here and press ENTER: " TARGET_DIR

# Strip quotes if dragged folder formatting contains them
TARGET_DIR="${TARGET_DIR%\"}"
TARGET_DIR="${TARGET_DIR#\"}"

python3 vibe_check.py "$TARGET_DIR" --out vibe-report.json --html vibe-report.html

echo ""
echo "[Scan Complete]"
echo "  JSON report: vibe-report.json"
echo "  HTML report: vibe-report.html"
echo ""
echo "Opening HTML report in your browser..."
if command -v open >/dev/null 2>&1; then
    open vibe-report.html        # macOS
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open vibe-report.html    # Linux
else
    echo "Could not auto-open. Open vibe-report.html manually."
fi

echo ""
read -p "Press ENTER to exit..."
