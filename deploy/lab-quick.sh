#!/bin/bash
# =============================================================================
# Quick Lab Commands - Source this file or run directly
# =============================================================================
# Usage:
#   source deploy/lab-quick.sh  # Then use: lab-status, lab-restart, etc.
#   OR
#   ./deploy/lab-quick.sh status
# =============================================================================

LAB_SERVER="access-engineering.nl"
LAB_DIR="/opt/pypnm-gui-lab"

# If sourced, create aliases
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    lab-status() {
        ssh $LAB_SERVER "$LAB_DIR/deploy/lab-deploy.sh status"
    }
    
    lab-restart() {
        ssh $LAB_SERVER "sudo $LAB_DIR/deploy/lab-deploy.sh restart"
    }
    
    lab-deploy() {
        ssh $LAB_SERVER "sudo $LAB_DIR/deploy/lab-deploy.sh deploy"
    }
    
    lab-health() {
        ssh $LAB_SERVER "$LAB_DIR/deploy/lab-deploy.sh health"
    }
    
    lab-logs() {
        ssh $LAB_SERVER "docker logs pypnm-gui-lab --tail 50 && docker logs pypnm-agent-lab --tail 20"
    }
    
    lab-fix() {
        ssh $LAB_SERVER "sudo $LAB_DIR/deploy/lab-deploy.sh fix"
    }
    
    echo "Lab commands available: lab-status, lab-restart, lab-deploy, lab-health, lab-logs, lab-fix"
else
    # Run directly
    case "${1:-help}" in
        status)
            ssh $LAB_SERVER "$LAB_DIR/deploy/lab-deploy.sh status"
            ;;
        restart)
            ssh $LAB_SERVER "sudo $LAB_DIR/deploy/lab-deploy.sh restart"
            ;;
        deploy)
            ssh $LAB_SERVER "sudo $LAB_DIR/deploy/lab-deploy.sh deploy"
            ;;
        health)
            ssh $LAB_SERVER "$LAB_DIR/deploy/lab-deploy.sh health"
            ;;
        logs)
            ssh $LAB_SERVER "docker logs pypnm-gui-lab --tail 50 && echo '---' && docker logs pypnm-agent-lab --tail 20"
            ;;
        fix)
            ssh $LAB_SERVER "sudo $LAB_DIR/deploy/lab-deploy.sh fix"
            ;;
        ssh)
            ssh $LAB_SERVER
            ;;
        *)
            echo "Usage: $0 {status|restart|deploy|health|logs|fix|ssh}"
            echo ""
            echo "Quick commands to manage PyPNM Lab environment"
            echo ""
            echo "Or source this file to get shell functions:"
            echo "  source $0"
            echo "  lab-status"
            ;;
    esac
fi
