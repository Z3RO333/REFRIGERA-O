#!/bin/bash

echo "[startup] Starting Redis..."
redis-server --appendonly no --save "" --loglevel warning --daemonize no &
REDIS_PID=$!

echo "[startup] Waiting for Redis to be ready..."
for i in $(seq 1 50); do
    if redis-cli ping 2>/dev/null | grep -q PONG; then
        echo "[startup] Redis ready (pid $REDIS_PID)"
        break
    fi
    sleep 0.2
done

echo "[startup] Starting uvicorn on port ${WEBSITES_PORT:-${PORT:-8000}}..."
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${WEBSITES_PORT:-${PORT:-8000}}" \
    --workers 2 \
    --log-level info
