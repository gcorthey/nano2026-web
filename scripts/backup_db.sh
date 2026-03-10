#!/bin/bash
set -euo pipefail

DB_PATH="/home/gcorthey/congreso_nano/congreso.db"
S3_BUCKET="nano2026-backups"
LOG_FILE="/home/gcorthey/congreso_nano/backup.log"
RETENTION_DAYS=30

export AWS_PROFILE=nano2026

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

log "=== Iniciando backup NANO2026 ==="

[[ -f "$DB_PATH" ]] || { log "ERROR: No se encontró $DB_PATH"; exit 1; }

TIMESTAMP=$(date '+%Y-%m-%d_%H-%M')
DATE=$(date '+%Y-%m-%d')
TMP_DIR=$(mktemp -d)
TMP_DB="$TMP_DIR/congreso_${TIMESTAMP}.db"
TMP_GZ="${TMP_DB}.gz"

log "Creando snapshot..."
sqlite3 "$DB_PATH" ".backup '$TMP_DB'"

log "Comprimiendo..."
gzip -9 "$TMP_DB"

SIZE=$(du -sh "$TMP_GZ" | cut -f1)
log "Tamaño: $SIZE"

log "Subiendo a S3..."
aws s3 cp "$TMP_GZ" "s3://$S3_BUCKET/daily/congreso_${DATE}.db.gz" \
    --storage-class STANDARD_IA

aws s3 cp "$TMP_GZ" "s3://$S3_BUCKET/hourly/congreso_${TIMESTAMP}.db.gz" \
    --storage-class STANDARD_IA

rm -rf "$TMP_DIR"
log "✓ Backup completado"
