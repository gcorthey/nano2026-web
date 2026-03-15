#!/bin/bash
set -euo pipefail

BACKUP_DIR="/mnt/backups"
LOG_DIR="${BACKUP_DIR}/logs"
DATE="$(date +%Y-%m-%d)"
IMAGE_PATH="${BACKUP_DIR}/rpi-${DATE}.img"
LOG_FILE="${LOG_DIR}/backup-${DATE}.log"
AWS_PROFILE="${AWS_PROFILE:-nano2026}"
S3_DEST="${S3_DEST:-s3://nano2026-backups/snapshots/}"
WORK_DIR="${WORK_DIR:-$HOME}"

mkdir -p "${BACKUP_DIR}" "${LOG_DIR}"

exec > >(tee -a "${LOG_FILE}") 2>&1

echo "=== Backup started: $(date) ==="

cd "${WORK_DIR}"

printf "%s\n\n1000\ny\n" "${IMAGE_PATH}" | sudo /usr/local/bin/image-backup

echo "Uploading to S3..."
aws --profile "${AWS_PROFILE}" s3 cp "${IMAGE_PATH}" "${S3_DEST}"

echo "Removing old local backups..."
find "${BACKUP_DIR}" -maxdepth 1 -type f -name "rpi-*.img" -mtime +2 -delete
find "${LOG_DIR}" -maxdepth 1 -type f -name "backup-*.log" -mtime +30 -delete

echo "=== Backup finished: $(date) ==="
