#!/bin/bash
# Redis Cache Management Script

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

REDIS_HOST="${REDIS_HOST:-eve-li-redis}"
REDIS_PORT="${REDIS_PORT:-6379}"

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

show_help() {
    cat << EOF
${GREEN}Redis Cache Management${NC}

${YELLOW}Usage:${NC}
    $0 [OPTIONS] ACTION

${YELLOW}Actions:${NC}
    flush               Flush all cache keys
    flush-modems        Flush only modem cache (keys: modems:*)
    flush-cmts          Flush only CMTS cache (keys: cmts:*)
    list                List all cache keys
    stats               Show Redis stats
    ping                Test Redis connection

${YELLOW}Options:${NC}
    -h, --host HOST     Redis host (default: eve-li-redis)
    -p, --port PORT     Redis port (default: 6379)
    --help              Show this help

${YELLOW}Examples:${NC}
    $0 flush                    # Flush all cache
    $0 flush-modems             # Flush only modem cache
    $0 list                     # List all keys
    $0 stats                    # Show Redis stats

EOF
}

# Parse arguments
ACTION=""
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--host)
            REDIS_HOST="$2"
            shift 2
            ;;
        -p|--port)
            REDIS_PORT="$2"
            shift 2
            ;;
        --help)
            show_help
            exit 0
            ;;
        flush|flush-modems|flush-cmts|list|stats|ping)
            ACTION="$1"
            shift
            ;;
        *)
            log_warning "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

if [ -z "$ACTION" ]; then
    log_warning "No action specified"
    show_help
    exit 1
fi

# Check if redis-cli is available
if ! command -v redis-cli &> /dev/null; then
    log_warning "redis-cli not found, trying docker..."
    REDIS_CMD="docker exec -it pypnmgui-redis-1 redis-cli"
else
    REDIS_CMD="redis-cli -h $REDIS_HOST -p $REDIS_PORT"
fi

log_info "Using Redis at $REDIS_HOST:$REDIS_PORT"

case $ACTION in
    ping)
        log_info "Testing Redis connection..."
        if $REDIS_CMD PING | grep -q PONG; then
            log_success "Redis is responding"
        else
            log_warning "Redis is not responding"
            exit 1
        fi
        ;;
    
    flush)
        log_warning "This will flush ALL cache keys!"
        read -p "Are you sure? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "Flushing all cache..."
            $REDIS_CMD FLUSHDB
            log_success "All cache flushed"
        else
            log_info "Cancelled"
        fi
        ;;
    
    flush-modems)
        log_info "Flushing modem cache (modems:*)..."
        KEYS=$($REDIS_CMD KEYS "modems:*")
        if [ -z "$KEYS" ]; then
            log_info "No modem cache keys found"
        else
            echo "$KEYS" | xargs -r $REDIS_CMD DEL
            COUNT=$(echo "$KEYS" | wc -l)
            log_success "Flushed $COUNT modem cache keys"
        fi
        ;;
    
    flush-cmts)
        log_info "Flushing CMTS cache (cmts:*)..."
        KEYS=$($REDIS_CMD KEYS "cmts:*")
        if [ -z "$KEYS" ]; then
            log_info "No CMTS cache keys found"
        else
            echo "$KEYS" | xargs -r $REDIS_CMD DEL
            COUNT=$(echo "$KEYS" | wc -l)
            log_success "Flushed $COUNT CMTS cache keys"
        fi
        ;;
    
    list)
        log_info "Listing all cache keys..."
        $REDIS_CMD KEYS "*"
        ;;
    
    stats)
        log_info "Redis stats:"
        echo ""
        $REDIS_CMD INFO stats | grep -E "total_commands_processed|instantaneous_ops_per_sec|keyspace_hits|keyspace_misses"
        echo ""
        log_info "Keyspace:"
        $REDIS_CMD INFO keyspace
        echo ""
        log_info "Memory:"
        $REDIS_CMD INFO memory | grep -E "used_memory_human|used_memory_peak_human|maxmemory_human"
        ;;
    
    *)
        log_warning "Unknown action: $ACTION"
        show_help
        exit 1
        ;;
esac
