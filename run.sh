#!/usr/bin/env bash
# PCB Inspector launcher for Linux and macOS.
#
#   ./run.sh                 create .venv (first run), install deps, start the app
#   ./run.sh --test          install test deps and run the test suite
#   ./run.sh --skip-install  start without checking/installing dependencies
#   ./run.sh --no-easyocr    skip the optional EasyOCR/PyTorch download
#
# Override the interpreter with:  PYTHON=python3.12 ./run.sh
set -euo pipefail

cd "$(dirname "$0")"

MODE="app"
SKIP_INSTALL=0
NO_EASYOCR=0
for arg in "$@"; do
    case "$arg" in
        --test|-t)       MODE="test" ;;
        --skip-install)  SKIP_INSTALL=1 ;;
        --no-easyocr)    NO_EASYOCR=1 ;;
        -h|--help)       sed -n '2,10p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg (use --help)"; exit 2 ;;
    esac
done

# ---- find a Python >= 3.10 ----
find_python() {
    for candidate in "${PYTHON:-}" python3.13 python3.12 python3.11 python3.10 python3 python; do
        [ -z "$candidate" ] && continue
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            echo "$candidate"; return 0
        fi
    done
    return 1
}

VENV_DIR=".venv"
VENV_PY="$VENV_DIR/bin/python"

if [ ! -x "$VENV_PY" ]; then
    if ! BASE_PY="$(find_python)"; then
        echo "ERROR: Python 3.10 or newer is required. Install it from https://www.python.org/downloads/" >&2
        exit 1
    fi
    echo ">> Creating virtual environment with $BASE_PY ..."
    if ! "$BASE_PY" -m venv "$VENV_DIR"; then
        echo "ERROR: could not create the virtual environment." >&2
        echo "       On Debian/Ubuntu install it with: sudo apt install python3-venv" >&2
        exit 1
    fi
    "$VENV_PY" -m pip install --upgrade pip >/dev/null
fi

# ---- install dependencies only when the requirements file changed ----
install_reqs() {
    local req_file="$1"
    local stamp="$VENV_DIR/.$(basename "$req_file").sha256"
    local digest
    digest="$("$VENV_PY" -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$req_file")"
    if [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$digest" ]; then
        return 0
    fi
    echo ">> Installing dependencies from $req_file ..."
    if [ "$NO_EASYOCR" = "1" ]; then
        grep -viE '^\s*easyocr' "$req_file" > "$VENV_DIR/.req-filtered.txt"
        "$VENV_PY" -m pip install -r "$VENV_DIR/.req-filtered.txt"
    else
        "$VENV_PY" -m pip install -r "$req_file"
        echo "$digest" > "$stamp"
    fi
}

if [ "$SKIP_INSTALL" = "0" ]; then
    if [ "$MODE" = "test" ]; then
        install_reqs requirements-dev.txt
    else
        install_reqs requirements.txt
    fi
fi

# pyzbar needs the native zbar library; warn (QR still works via OpenCV).
if ! "$VENV_PY" -c "import pyzbar.pyzbar" >/dev/null 2>&1; then
    case "$(uname -s)" in
        Darwin) echo "NOTE: zbar library not found - barcode reading limited to QR. Fix: brew install zbar" ;;
        *)      echo "NOTE: zbar library not found - barcode reading limited to QR. Fix: sudo apt install libzbar0" ;;
    esac
    if [ "$(uname -s)" = "Darwin" ] && [ -d /opt/homebrew/lib ]; then
        # Homebrew on Apple Silicon installs outside the default library path.
        export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:${DYLD_FALLBACK_LIBRARY_PATH:-}"
    fi
fi

if [ "$MODE" = "test" ]; then
    echo ">> Running tests ..."
    QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" exec "$VENV_PY" -m pytest tests ${PYTEST_ARGS:--q}
else
    echo ">> Starting PCB Inspector ..."
    exec "$VENV_PY" main.py
fi
