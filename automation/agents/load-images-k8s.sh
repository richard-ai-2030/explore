#!/usr/bin/env bash
set -euo pipefail

PULL_IMAGES="false"
IMAGE_REGISTRY="ghcr.io/richard-ai-2030"
IMAGE_TAG="version3"
CLUSTER_NAME="staging"

DOMAIN="${1:-}"
SERVICE="${2:-}"

TARGET_DIR="services/${DOMAIN}"

load_kind_image() {
  local image="$1"

  if [ "$PULL_IMAGES" = "true" ]; then
    docker pull "${IMAGE_REGISTRY}/${image}:${IMAGE_TAG}"
    docker tag "${IMAGE_REGISTRY}/${image}:${IMAGE_TAG}" "${image}:${IMAGE_TAG}"
  fi

  kind load docker-image "${image}" --name "${CLUSTER_NAME}"
  # k3d image import "${image}" -c "${CLUSTER_NAME}"
}

resolve_image_name() {
  local name="$1"
  echo "${name}:${IMAGE_TAG}"
}

process_service() {
  local service_name="$1"
  local service_dir="$2"

  if [ -f "$service_dir/Dockerfile" ]; then
    image="$(resolve_image_name "$service_name")"

    if docker image inspect "$image" >/dev/null 2>&1; then
      load_kind_image "$image"
    else
      echo "Skipping $service_name: image not found locally -> $image"
    fi
  else
    echo "Skipping $service_name: no Dockerfile found"
  fi
}

# Load only a specific service if SERVICE is provided
if [ -n "$SERVICE" ]; then
  SERVICE_DIR="${TARGET_DIR}/${SERVICE}"

  if [ ! -d "$SERVICE_DIR" ]; then
    echo "Error: Service directory not found: $SERVICE_DIR"
    exit 1
  fi

  process_service "$SERVICE" "$SERVICE_DIR"

else
  # Load all services under the domain
  for dir in "${TARGET_DIR}"/*; do
    [ -d "$dir" ] || continue

    service_name="$(basename "$dir")"

    process_service "$service_name" "$dir"
  done
fi

echo "Done."