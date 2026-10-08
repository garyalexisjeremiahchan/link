#!/usr/bin/env bash
# deploy.sh — Deploy FCC Link to the shared Azure VM (4.193.171.7)
# Run from the dev machine (Git Bash on Windows).
# Usage: ./deploy.sh [user@vm-host]   (default: $FCC_LINK_VM, else azureuser@4.193.171.7)
set -euo pipefail
cd "$(dirname "$0")"

VM="${1:-${FCC_LINK_VM:-azureuser@4.193.171.7}}"
REMOTE_DIR="apps/fcc.li"

# Python: prefer local .venv, fall back to PATH
PYTHON="${PYTHON:-.venv/Scripts/python.exe}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${PYTHON:-.venv/bin/python}"
fi
[[ -x "$PYTHON" ]] || PYTHON=python

echo "=== [1/6] Validating git status ==="
if [[ -n "$(git status --porcelain)" ]]; then
  echo "x Working tree is dirty. Commit or stash changes before deploying."
  exit 1
fi

echo "=== [2/6] Running automated test suite locally ==="
"$PYTHON" -m pytest tests/ -v || { echo "x Local tests failed! Aborting deployment."; exit 1; }

echo "=== [3/6] Shipping codebase to $VM ($REMOTE_DIR) ==="
git archive --format=tar.gz HEAD | ssh "$VM" \
  "mkdir -p $REMOTE_DIR \
   && find $REMOTE_DIR -mindepth 1 -maxdepth 1 ! -name .env ! -name data -exec rm -rf {} + \
   && tar xzf - -C $REMOTE_DIR"

echo "=== [4/6] Setting up environment and data directories ==="
ssh "$VM" "
  mkdir -p $REMOTE_DIR/data
  if [[ ! -f $REMOTE_DIR/.env ]]; then
    SECRET=\$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(32))')
    cat <<EOF > $REMOTE_DIR/.env
APP_NAME=FCC Link
PORTAL_DOMAIN=link.gajc.site
MANAGED_DOMAINS=fcc.li,amp.ad,link.gajc.site
DEFAULT_SUPERADMIN=freecommunitychurchsingapore@gmail.com
DATABASE_URL=sqlite+aiosqlite:///data/app.db
SECRET_KEY=\$SECRET
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=https://link.gajc.site/auth/callback
DEV_AUTH_BYPASS=true
EOF
    echo 'Created initial .env with generated SECRET_KEY (DEV_AUTH_BYPASS=true).'
  fi
"

echo "=== [5/6] Verifying SSL certificate and updating Nginx configuration ==="
ssh "$VM" "
  mkdir -p pentecost/nginx/conf.d

  # Check if SSL certificate exists for link.gajc.site
  if [[ ! -f /etc/letsencrypt/live/link.gajc.site/fullchain.pem ]]; then
    echo 'SSL cert for link.gajc.site not found. Requesting via Certbot webroot...'
    
    # Ensure temporary HTTP-only config is in place so certbot challenge passes
    cat <<'EOF' > pentecost/nginx/conf.d/link.conf
server {
    listen 80;
    server_name link.gajc.site;
    location /.well-known/acme-challenge/ {
        root /var/www/pentecost;
    }
}
EOF
    docker exec pentecost-nginx-1 nginx -t && docker exec pentecost-nginx-1 nginx -s reload
    
    sudo certbot certonly --webroot -w /home/azureuser/pentecost/web \
      -d link.gajc.site \
      --non-interactive --agree-tos --register-unsafely-without-email || true
  fi

  # Deploy production Nginx configuration
  if [[ -f /etc/letsencrypt/live/link.gajc.site/fullchain.pem ]]; then
    cp $REMOTE_DIR/deploy/nginx-link.conf pentecost/nginx/conf.d/link.conf
    echo 'Copied full HTTPS Nginx config to pentecost/nginx/conf.d/link.conf'
  else
    echo 'Warning: SSL certificate could not be issued yet. Keeping HTTP-only config.'
  fi

  # Safely test and reload Nginx
  docker exec pentecost-nginx-1 nginx -t
  docker exec pentecost-nginx-1 nginx -s reload
"

echo "=== [6/6] Building container & launching fcc-li-web ==="
ssh "$VM" "
  cd $REMOTE_DIR
  docker compose build
  docker compose up -d
"

echo "=== Testing container health and deployment ==="
ssh "$VM" "
  sleep 3
  docker ps --filter name=fcc-li-web
  docker logs --tail 20 fcc-li-web
"

echo "✓ Deployment complete! Portal live at https://link.gajc.site"
