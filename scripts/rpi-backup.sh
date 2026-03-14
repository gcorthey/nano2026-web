#!/bin/bash
set -euo pipefail

BACKUP_DIR="/mnt/backups"
LOG_DIR="${BACKUP_DIR}/logs"
DATE="$(date +%Y-%m-%d)"
IMAGE_PATH="${BACKUP_DIR}/rpi-${DATE}.img"
LOG_FILE="${LOG_DIR}/backup-${DATE}.log"
AWS_PROFILE="nano2026"
S3_DEST="s3://nano2026-backups/snapshots/"

mkdir -p "${BACKUP_DIR}" "${LOG_DIR}"

exec > >(tee -a "${LOG_FILE}") 2>&1

echo "=== Backup started: $(date) ==="

cd /home/gcorthey

printf "%s\n\n1000\ny\n" "${IMAGE_PATH}" | sudo /usr/local/bin/image-backup

echo "Uploading to S3..."
aws --profile "${AWS_PROFILE}" s3 cp "${IMAGE_PATH}" "${S3_DEST}"

echo "Removing old local backups..."
find "${BACKUP_DIR}" -maxdepth 1 -type f -name "rpi-*.img" -mtime +7 -delete
find "${LOG_DIR}" -maxdepth 1 -type f -name "backup-*.log" -mtime +30 -delete

echo "=== Backup finished: $(date) ==="
