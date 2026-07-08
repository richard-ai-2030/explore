#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

install_if_needed() {
  if [ ! -d "node_modules" ]; then
    npm install
  fi
}

( echo "starting Marketing (Next.js) app..."
  cd "$ROOT_DIR/frontends/marketing-app"
  install_if_needed
  export NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8888/api"
  export NEXT_PUBLIC_BASE_PATH=""
  npx next dev --hostname 0.0.0.0 --port 8080
) &

( echo "starting Production (Vue) app..."
  cd "$ROOT_DIR/frontends/production-app"
  install_if_needed
  export VITE_API_BASE_URL="http://127.0.0.1:8888/api"
  npx vite --host 0.0.0.0 --port 8081
) &

( echo "starting Talents (Angular) app..."
  cd "$ROOT_DIR/frontends/hr-app"
  install_if_needed
  export API_BASE_URL="http://127.0.0.1:8888/api"
  export CI=true
  npx ng analytics disable >/dev/null 2>&1 || true
  npx ng serve --host 0.0.0.0 --port 8082 --no-open
)
