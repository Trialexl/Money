#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

DOCKERHUB_NAMESPACE="${DOCKERHUB_NAMESPACE:-trialexl}"
IMAGE_TAG="${1:-${IMAGE_TAG:-latest}}"
PLATFORM="${PLATFORM:-linux/amd64}"
BACKEND_IMAGE="${BACKEND_IMAGE:-${DOCKERHUB_NAMESPACE}/money-backend}"
FRONTEND_IMAGE="${FRONTEND_IMAGE:-${DOCKERHUB_NAMESPACE}/money-frontend}"
NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-/api/v1}"

BACKEND_REF="${BACKEND_IMAGE}:${IMAGE_TAG}"
FRONTEND_REF="${FRONTEND_IMAGE}:${IMAGE_TAG}"

step() {
  printf '\n==> %s\n' "$1"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || fail "Docker is not installed."
docker info >/dev/null 2>&1 || fail "Docker daemon is not running."
docker buildx version >/dev/null 2>&1 || fail "Docker Buildx is not available."

if [[ ! "$IMAGE_TAG" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]*$ ]]; then
  fail "Invalid Docker image tag: ${IMAGE_TAG}"
fi

step "Build and push backend: ${BACKEND_REF} (${PLATFORM})"
docker buildx build \
  --platform "$PLATFORM" \
  --tag "$BACKEND_REF" \
  --push \
  "$ROOT_DIR/moneybackend"

step "Build and push frontend: ${FRONTEND_REF} (${PLATFORM})"
docker buildx build \
  --platform "$PLATFORM" \
  --build-arg "NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}" \
  --tag "$FRONTEND_REF" \
  --push \
  "$ROOT_DIR/frontmoney"

step "Verify published images"
docker buildx imagetools inspect "$BACKEND_REF" >/dev/null
printf 'Backend:  %s\n' "$BACKEND_REF"
docker buildx imagetools inspect "$FRONTEND_REF" >/dev/null
printf 'Frontend: %s\n' "$FRONTEND_REF"

step "Images were built and pushed successfully"
