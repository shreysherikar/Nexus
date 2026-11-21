#!/bin/sh
set -e

echo "==> Starting NEXUS Backend entrypoint..."

# Wait for database connectivity if DATABASE_URL is PostgreSQL
if [ -n "$DATABASE_URL" ] && echo "$DATABASE_URL" | grep -qv "sqlite"; then
  echo "==> Checking database connectivity..."
  python - <<'EOF'
import os
import sys
import time
from sqlalchemy import create_engine, text

db_url = os.getenv("DATABASE_URL")
if not db_url:
    sys.exit(0)

max_retries = 30
for attempt in range(1, max_retries + 1):
    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"==> Database connection established on attempt {attempt}.")
        sys.exit(0)
    except Exception as exc:
        print(f"==> Database connection attempt {attempt}/{max_retries} failed ({exc}). Retrying in 2s...")
        time.sleep(2)

print("==> ERROR: Could not connect to database within timeout limit.")
sys.exit(1)
EOF
fi

# Run Alembic schema migrations
echo "==> Running Alembic schema migrations..."
alembic upgrade head
echo "==> Alembic migrations completed successfully."

# Execute main container command
echo "==> Launching application process: $@"
exec "$@"
