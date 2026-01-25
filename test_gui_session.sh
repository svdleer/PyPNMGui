#!/bin/bash
# =============================================================================
# GUI Session Test Runner
# =============================================================================
# Runs automated browser tests against the GUI
#
# Usage:
#   ./test_gui_session.sh [quick|full]
#
# Prerequisites:
#   pip install playwright
#   playwright install chromium
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Check if venv exists
if [ ! -d "venv" ]; then
    log_info "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
log_info "Activating virtual environment..."
source venv/bin/activate

# Check for playwright
if ! python -c "import playwright" 2>/dev/null; then
    log_info "Installing playwright..."
    pip install playwright pytest-playwright
    playwright install chromium
fi

# Determine test mode
TEST_MODE=${1:-full}

case "$TEST_MODE" in
    quick)
        log_info "Running quick CMTS check..."
        python test_gui_session.py quick
        ;;
    full)
        log_info "Running full UTSC session test..."
        python test_gui_session.py
        ;;
    remote)
        log_info "Running test against remote server..."
        # SSH tunnel to access-engineering.nl
        log_info "Setting up SSH tunnel to access-engineering.nl..."
        ssh -f -N -L 5050:localhost:5050 access-engineering.nl
        sleep 2
        python test_gui_session.py
        # Kill tunnel
        pkill -f "ssh.*5050:localhost:5050"
        ;;
    *)
        log_error "Unknown mode: $TEST_MODE"
        echo "Usage: $0 [quick|full|remote]"
        exit 1
        ;;
esac

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    log_success "Test passed!"
else
    log_error "Test failed!"
fi

exit $EXIT_CODE
