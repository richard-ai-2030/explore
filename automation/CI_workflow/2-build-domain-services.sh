#!/usr/bin/env bash
set -euo pipefail

PUSH_IMAGES="false"
IMAGE_REGISTRY="ghcr.io/richard-ai-2030"
IMAGE_TAG="version3"

DOMAIN="${1:-}"

if [ -z "$DOMAIN" ]; then
  echo "❌ Usage: $0 <DOMAIN>"
  echo "Example: $0 MARKETING"
  exit 1
fi

TARGET_DIR="services/${DOMAIN}"

if [ ! -d "$TARGET_DIR" ]; then
  echo "❌ Directory not found: $TARGET_DIR"
  exit 1
fi

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

echo "Scanning ${TARGET_DIR}/ ..."

for dir in "${TARGET_DIR}"/*; do
  [ -d "$dir" ] || continue
  service_name="$(basename "$dir")"

  if [ -f "$dir/Dockerfile" ]; then
    build_and_push "$service_name" "$dir"
  else
    echo "Skipping $service_name: no Dockerfile found"
  fi
done

echo "Done."