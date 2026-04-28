#!/usr/bin/env bash
set -euo pipefail

IMAGE_REGISTRY="${IMAGE_REGISTRY:-GitHub.images.registry.explore}"
IMAGE_TAG="${IMAGE_TAG:-version3}"
CLUSTER_TYPE="${CLUSTER_TYPE:-kind}"
CLUSTER_NAME="${CLUSTER_NAME:-staging}"

# ✅ Get domain from argument
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

load_kind_image() {
  local image="$1"
  echo "==> kind load docker-image ${image} --name ${CLUSTER_NAME}"
  kind load docker-image "${image}" --name "${CLUSTER_NAME}"
}

load_k3d_image() {
  local image="$1"
  echo "==> k3d image import ${image} -c ${CLUSTER_NAME}"
  k3d image import "${image}" -c "${CLUSTER_NAME}"
}

load_image() {
  local image="$1"

  case "${CLUSTER_TYPE}" in
    kind)
      load_kind_image "${image}"
      ;;
    k3d)
      load_k3d_image "${image}"
      ;;
    *)
      echo "Unsupported CLUSTER_TYPE: ${CLUSTER_TYPE}"
      echo "Use CLUSTER_TYPE=kind or CLUSTER_TYPE=k3d"
      exit 1
      ;;
  esac
}

resolve_image_name() {
  local name="$1"
  echo "${name}:${IMAGE_TAG}"
  # echo "${IMAGE_REGISTRY}/${name}:${IMAGE_TAG}"
}

echo "Scanning ${TARGET_DIR}/ ..."

for dir in "${TARGET_DIR}"/*; do
  [ -d "$dir" ] || continue

  service_name="$(basename "$dir")"

  if [ -f "$dir/Dockerfile" ]; then
    image="$(resolve_image_name "$service_name")"

    if docker image inspect "$image" >/dev/null 2>&1; then
      load_image "$image"
    else
      echo "Skipping $service_name: image not found locally -> $image"
    fi
  else
    echo "Skipping $service_name: no Dockerfile found"
  fi
done

echo "Done."