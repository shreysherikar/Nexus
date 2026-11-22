#!/bin/sh
set -e

echo "==> Starting NEXUS Backend entrypoint..."

# Construct DATABASE_URL from configured environment variables if not explicitly provided
if [ -z "$DATABASE_URL" ] && [ -n "$POSTGRES_PASSWORD" ]; then
  DATABASE_URL=$(python - <<'EOF'
import os
from sqlalchemy.engine import URL
user = os.getenv("POSTGRES_USER", "nexus_user")
pwd = os.getenv("POSTGRES_PASSWORD")
host = os.getenv("POSTGRES_HOST", "postgres")
port_str = os.getenv("POSTGRES_PORT", "5432")
port = int(port_str) if port_str.isdigit() else 5432
db = os.getenv("POSTGRES_DB", "nexus_db")
print(URL.create("postgresql+psycopg", username=user, password=pwd, host=host, port=port, database=db).render_as_string(hide_password=False))
EOF
)
  export DATABASE_URL
fi

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
        err_type = type(exc).__name__
        print(f"==> Database connection attempt {attempt}/{max_retries} failed [{err_type}]. Retrying in 2s...")
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
