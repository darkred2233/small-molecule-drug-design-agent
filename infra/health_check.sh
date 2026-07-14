#!/usr/bin/env bash
#
# Health check script for infrastructure services
#
# Usage: ./health_check.sh

set -e

echo "=== Infrastructure Health Check ==="
echo ""

# Check PostgreSQL
echo "Checking PostgreSQL..."
if pg_isready -h localhost -p 5432 -U medagent > /dev/null 2>&1; then
    echo "✓ PostgreSQL is running"
else
    echo "✗ PostgreSQL is not responding"
fi

# Check MinIO
echo "Checking MinIO..."
if curl -sf http://localhost:9000/minio/health/live > /dev/null 2>&1; then
    echo "✓ MinIO is running"
else
    echo "✗ MinIO is not responding"
fi

# Check Docker containers
echo ""
echo "Docker container status:"
docker compose ps

echo ""
echo "=== Health Check Complete ==="
