#!/usr/bin/env bash
# Generate a unique ADMIN_SECRET for AutoApply (Railway / Fly / .env).
# Usage: ./scripts/gen_admin_secret.sh
set -euo pipefail
printf 'ADMIN_SECRET=%s\n' "$(openssl rand -hex 32)"
