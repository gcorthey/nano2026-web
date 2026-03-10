#!/bin/bash
set -euo pipefail

DB_PATH="/home/gcorthey/congreso_nano/congreso.db"
S3_BUCKET="nano2026-backups"
DATE="${1:-}"

export AWS_PROFILE=nano2026

# Si no se pasa fecha, mostrar backups disponibles
if [[ -z "$DATE" ]]; then
    echo "Backups disponibles:"
    aws s3 ls "s3://$S3_BUCKET/daily/" | awk '{print $4}' | grep -oP '\d{4}-\d{2}-\d{2}'
    echo ""
    echo "Uso: $0 YYYY-MM-DD"
    exit 0
fi

KEY="daily/congreso_${DATE}.db.gz"

echo "⚠️  Restaurando backup del $DATE"
echo "   Destino: $DB_PATH"
read -rp "   ¿Confirmar? [s/N] " CONFIRM
[[ "$CONFIRM" =~ ^[sS]$ ]] || { echo "Cancelado."; exit 0; }

# Backup del estado actual
SAVE="${DB_PATH}.pre-restore.$(date +%s)"
cp "$DB_PATH" "$SAVE"
echo "→ Estado actual guardado en: $SAVE"

# Descargar y descomprimir
TMP=$(mktemp)
aws s3 cp "s3://$S3_BUCKET/$KEY" "${TMP}.gz"
gunzip "${TMP}.gz"

# Verificar integridad
INTEGRITY=$(sqlite3 "$TMP" "PRAGMA integrity_check;")
if [[ "$INTEGRITY" != "ok" ]]; then
    echo "ERROR: Backup corrupto. Abortando."
    rm -f "$TMP"
    exit 1
fi

cp "$TMP" "$DB_PATH"
rm -f "$TMP"
echo "✓ Restauración completada."
