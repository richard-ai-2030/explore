#!/usr/bin/env bash
set -euo pipefail

PUSH_IMAGES="false"
IMAGE_REGISTRY="ghcr.io/richard-ai-2030"
IMAGE_TAG="version3"

DOMAIN="${1:-}"
SERVICE="${2:-}"

TARGET_DIR="services/${DOMAIN}"

build_and_push() {
  local name="$1"
  local context="$2"

  echo "==> Building ${name} from ${context}"
  docker build -t "${name}:${IMAGE_TAG}" "$context"

  if [ "$PUSH_IMAGES" = "true" ]; then
    echo "==> Pushing ${IMAGE_REGISTRY}/${name}:${IMAGE_TAG}"
    docker tag "${name}:${IMAGE_TAG}" "${IMAGE_REGISTRY}/${name}:${IMAGE_TAG}"
    docker push "${IMAGE_REGISTRY}/${name}:${IMAGE_TAG}"
  fi
}

# Build only a specific service if SERVICE is provided
if [ -n "$SERVICE" ]; then
  SERVICE_DIR="${TARGET_DIR}/${SERVICE}"

  if [ ! -d "$SERVICE_DIR" ]; then
    echo "Error: Service directory not found: $SERVICE_DIR"
    exit 1
  fi

  if [ -f "$SERVICE_DIR/Dockerfile" ]; then
    build_and_push "$SERVICE" "$SERVICE_DIR"
  else
    echo "Error: No Dockerfile found for service: $SERVICE"
    exit 1
  fi

else
  # Build all services under the domain
  for dir in "${TARGET_DIR}"/*; do
    [ -d "$dir" ] || continue
    service_name="$(basename "$dir")"

    if [ -f "$dir/Dockerfile" ]; then
      build_and_push "$service_name" "$dir"
    else
      echo "Skipping $service_name: no Dockerfile found"
    fi
  done
fi

echo "Done."