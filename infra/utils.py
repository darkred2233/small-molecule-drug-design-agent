"""
Infrastructure utilities for deployment and monitoring.

This module provides utilities for:
- Service health checks
- Database connection pooling
- File storage access
- Monitoring and metrics
"""

import time
from typing import Any

import psycopg2


def check_postgres_health(
    host: str = "localhost",
    port: int = 5432,
    user: str = "medagent",
    password: str = "",
    database: str = "medagent",
    timeout: int = 5,
) -> dict[str, Any]:
    """
    Check PostgreSQL health.

    Args:
        host: Database host
        port: Database port
        user: Database user
        password: Database password
        database: Database name
        timeout: Connection timeout in seconds

    Returns:
        Health check result dictionary
    """
    result = {
        "service": "postgresql",
        "status": "unknown",
        "message": "",
        "latency_ms": None,
    }

    try:
        start_time = time.time()
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            connect_timeout=timeout,
        )
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        conn.close()

        latency = (time.time() - start_time) * 1000
        result["status"] = "healthy"
        result["message"] = "PostgreSQL is responding"
        result["latency_ms"] = round(latency, 2)

    except psycopg2.OperationalError as exc:
        result["status"] = "unhealthy"
        result["message"] = f"Connection failed: {exc}"
    except Exception as exc:
        result["status"] = "error"
        result["message"] = f"Unexpected error: {exc}"

    return result


def check_minio_health(
    endpoint: str = "http://localhost:9000",
    timeout: int = 5,
) -> dict[str, Any]:
    """
    Check MinIO health.

    Args:
        endpoint: MinIO endpoint URL
        timeout: Request timeout in seconds

    Returns:
        Health check result dictionary
    """
    result = {
        "service": "minio",
        "status": "unknown",
        "message": "",
        "latency_ms": None,
    }

    try:
        import requests

        start_time = time.time()
        response = requests.get(
            f"{endpoint}/minio/health/live",
            timeout=timeout,
        )
        latency = (time.time() - start_time) * 1000

        if response.status_code == 200:
            result["status"] = "healthy"
            result["message"] = "MinIO is responding"
            result["latency_ms"] = round(latency, 2)
        else:
            result["status"] = "unhealthy"
            result["message"] = f"Unexpected status code: {response.status_code}"

    except Exception as exc:
        result["status"] = "error"
        result["message"] = f"Health check failed: {exc}"

    return result


def check_all_services() -> dict[str, Any]:
    """
    Check health of all infrastructure services.

    Returns:
        Dictionary with health check results for all services
    """
    return {
        "postgres": check_postgres_health(),
        "minio": check_minio_health(),
    }


def get_system_info() -> dict[str, Any]:
    """
    Get system information for monitoring.

    Returns:
        System information dictionary
    """
    import platform
    import sys

    return {
        "python_version": sys.version,
        "platform": platform.platform(),
        "architecture": platform.machine(),
    }
