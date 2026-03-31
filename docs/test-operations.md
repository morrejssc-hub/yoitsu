# Yoitsu Long-Running Test Guide

## Overview

This guide describes how to run long-duration tests (5-8 hours per round) to validate system stability.

## Quick Start

```bash
# 1. Prepare test tasks
ls test-tasks/  # Review available task templates

# 2. Run a full test round (8 hours)
./scripts/test-round.sh 480  # 480 minutes = 8 hours

# 3. Review results
cat test-runs/latest/report.md
```

## Scripts Reference

| Script | Purpose | Usage |
|--------|---------|-------|
| `test-round.sh` | Full test round (setup→monitor→backup→report) | `./scripts/test-round.sh [DURATION_MIN] [TASKS_DIR]` |
| `monitor.sh` | Continuous monitoring | `INTERVAL=30 ./scripts/monitor.sh` |
| `batch-submit.sh` | Submit multiple tasks | `./scripts/batch-submit.sh [TASKS_DIR]` |
| `health-check.sh` | Verify all services | `./scripts/health-check.sh` |
| `backup-test-data.sh` | Backup database and state | `./scripts/backup-test-data.sh [BACKUP_DIR]` |
| `cleanup-test-data.sh` | Clean volumes and containers | `./scripts/cleanup-test-data.sh` |
| `generate-report.sh` | Generate summary report | `./scripts/generate-report.sh [LOG_DIR]` |

## Configuration

### Workers

Current configuration (in `deploy/quadlet/trenni.dev.yaml`):
```yaml
max_workers: 8  # Parallel job execution
```

To change:
```bash
# Edit the config, then redeploy
vim deploy/quadlet/trenni.dev.yaml
./scripts/deploy-quadlet.sh --skip-build
```

### Test Duration

```bash
# 4 hour test
./scripts/test-round.sh 240

# 8 hour test (default)
./scripts/test-round.sh 480

# 12 hour test
./scripts/test-round.sh 720
```

## Monitoring

### Real-time Dashboard

```bash
# Text output every 60 seconds
./scripts/monitor.sh

# JSON output for parsing
OUTPUT_FORMAT=json ./scripts/monitor.sh

# Custom interval
INTERVAL=30 ./scripts/monitor.sh

# Limited duration (2 hours)
DURATION=7200 ./scripts/monitor.sh
```

### Status Check

```bash
# Quick status
uv run yoitsu status

# Service health
./scripts/health-check.sh

# Active tasks
uv run yoitsu tasks

# Task chain
uv run yoitsu tasks chain <task_id>
```

## Data Management

### Backup

```bash
# Backup before cleanup
./scripts/backup-test-data.sh

# Backup to custom location
./scripts/backup-test-data.sh /path/to/backup
```

Backup includes:
- PostgreSQL database dump
- Trenni state volume
- Pasloe data volume
- Service logs
- Task execution summary

### Cleanup

```bash
# After backup, clean everything
./scripts/cleanup-test-data.sh

# Force cleanup without backup check
FORCE=1 ./scripts/cleanup-test-data.sh
```

### Restore (if needed)

```bash
# Restore from backup
podman volume import yoitsu-dev-state test-backups/20260329-120000/yoitsu-dev-state.tar
podman volume import yoitsu-pasloe-data test-backups/20260329-120000/yoitsu-pasloe-data.tar

# Restore database
podman exec -i yoitsu-postgres psql -U yoitsu pasloe < test-backups/20260329-120000/pasloe-db.sql
```

## Test Tasks

Tasks are stored in `test-tasks/` directory:

| File | Purpose | Budget |
|------|---------|--------|
| `01-simple-file.yaml` | Basic file creation | 0.30 |
| `02-multi-file.yaml` | Multiple file operations | 0.40 |
| `03-spawn-test.yaml` | Spawn mode (planner→child→eval) | 0.50 |
| `04-version-bump.yaml` | External repo modification | 0.35 |

### Custom Tasks

Create new task files following this template:

```yaml
tasks:
  - goal: |
      Your task description here.
    team: default
    budget: 0.30  # Adjust based on complexity
    context:
      repo: https://github.com/org/repo.git
      init_branch: main
      new_branch: true
```

## Typical Test Round Output

```
test-runs/20260329-120000/
├── report.md           # Summary report
├── deploy.log          # Deployment log
├── submit.log          # Task submission log
├── monitor.log         # Continuous monitoring log
├── monitor.log.data    # CSV data for analysis
├── health.log          # Health check results
├── backup.log          # Backup operation log
└── backup/             # Backup data
    ├── pasloe-db.sql
    ├── yoitsu-dev-state.tar
    ├── yoitsu-pasloe-data.tar
    ├── status.json
    ├── events.json
    └── manifest.json
```

## Troubleshooting

### Services not starting

```bash
# Check service status
systemctl --user status yoitsu-postgres yoitsu-pasloe yoitsu-trenni

# Check logs
journalctl --user -u yoitsu-trenni -n 50

# Redeploy
./scripts/deploy-quadlet.sh
```

### Tasks stuck in pending

```bash
# Check if paused
curl http://127.0.0.1:8100/control/status | python3 -m json.tool

# Resume if paused
curl -X POST http://127.0.0.1:8100/control/resume
```

### Out of disk space

```bash
# Check disk usage
df -h

# Clean old backups
rm -rf test-backups/old-*

# Clean test runs
rm -rf test-runs/old-*

# Clean Docker/Podman
podman system prune -f
```

### Database connection issues

```bash
# Check PostgreSQL
podman exec yoitsu-postgres pg_isready

# Check connection params
cat ~/.config/containers/systemd/yoitsu/postgres.env
```

## Metrics to Watch

During long-running tests, monitor:

1. **Task success rate** - Should be > 80%
2. **Queue depth** - Should not grow unbounded
3. **Container count** - Should not leak (check `podman ps -a`)
4. **Disk usage** - Should not exceed 80%
5. **Memory usage** - Services should not grow unbounded
6. **Event count** - Pasloe events should not grow unbounded (use backup/cleanup cycle)