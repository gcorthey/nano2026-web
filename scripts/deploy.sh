#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
BRANCH="${BRANCH:-main}"
SERVICE_NAME="${SERVICE_NAME:-nano2026}"

cd "${REPO_DIR}"
git fetch origin "${BRANCH}"
git reset --hard "origin/${BRANCH}"
sudo systemctl restart "${SERVICE_NAME}"
