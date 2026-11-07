#!/usr/bin/env bash
# Backup diario de taller.db con rotacion (se queda con los ultimos 14).
# Se instala por cron en /etc/cron.d/tallerbot-backup (ve setup.sh).
set -euo pipefail

DESTINO="/var/backups/tallerbot"
FOLDER="/opt/tallerbot"
mkdir -p "$DESTINO"
cd "$FOLDER"

ARCHIVO="taller-$(date +%Y%m%d_%H%M%S).db"

# Backup consistente con la API nativa de SQLite (.backup copia aunque el
# bot este escribiendo en ese momento).
sqlite3 "$FOLDER/taller.db" ".backup '$DESTINO/$ARCHIVO'"

# Rotacion: conserva los 14 mas recientes
ls -1t "$DESTINO"/taller-*.db | tail -n +15 | xargs -r rm -f

echo "$(date '+%F %T') backup OK: $DESTINO/$ARCHIVO" >> "$DESTINO/backup.log"
