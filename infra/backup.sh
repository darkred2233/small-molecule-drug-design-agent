#!/usr/bin/env bash
#
# Backup script for PostgreSQL and MinIO data
#
# Usage: ./backup.sh [backup_dir]

set -e

BACKUP_DIR="${1:-.local/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

echo "=== Backup started at $TIMESTAMP ==="

# Backup PostgreSQL
echo "Backing up PostgreSQL..."
PG_BACKUP="$BACKUP_DIR/postgres_$TIMESTAMP.sql"
docker exec postgres pg_dump -U medagent medagent > "$PG_BACKUP"
echo "✓ PostgreSQL backup saved to $PG_BACKUP"

# Compress backup
gzip "$PG_BACKUP"
echo "✓ Compressed to ${PG_BACKUP}.gz"

# Note about MinIO backup
echo ""
echo "Note: MinIO data is stored in Docker volume 'minio_data'"
echo "To backup MinIO, use: docker run --rm -v minio_data:/data -v $BACKUP_DIR:/backup alpine tar czf /backup/minio_$TIMESTAMP.tar.gz -C /data ."

echo ""
echo "=== Backup complete ==="
