#!/usr/bin/env bash
# ================= SETUP DE TALLERBOT (Ubuntu 22/24, Oracle Free) ============
# Uso (en la VM de Oracle, dentro del repo clonado):
#   sudo bash deploy/setup.sh
#
# Hace: dependencias APT -> usuario/sitio /opt/tallerbot -> venv + deps
#       -> swap si hace falta -> firewall (solo SSH) -> systemd -> cron backup
set -euo pipefail

SITIO="/opt/tallerbot"

# ---------- 1.Paquetes del sistema ----------
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip sqlite3 git

# ---------- 2. Swap (por si la VM micro tiene 1 GB de RAM) ----------
if ! swapon --show | grep -q '/swapfile'; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "swap: 2G creado"
else
    echo "swap: ya existe"
fi

# ---------- 3. Sitio del bot en /opt/tallerbot ----------
id -u tallerbot >/dev/null 2>&1 || useradd --system --home "$SITIO" --shell /usr/sbin/nologin tallerbot

if [ ! -d "$SITIO/.git" ]; then
    echo ">> Clona primero el repo en $SITIO antes de correr este script."
    exit 1
fi

cd "$SITIO"
python3 -m venv venv
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt

# ---------- 4. Firewall: solo SSH (el bot sale a Telegram, no entra nada) ----------
apt-get install -y -qq ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
yes | ufw enable

# ---------- 5. Servicio systemd ----------
cp deploy/tallerbot.service /etc/systemd/system/
chown -R tallerbot:tallerbot "$SITIO"
chmod 700 "$SITIO/.env" 2>/dev/null || echo "RECUERDA: crear $SITIO/.env"
systemctl daemon-reload
systemctl enable --now tallerbot

# ---------- 6. Backup diario 03:15 ----------
install -m 755 deploy/backup.sh /usr/local/bin/tallerbot-backup
cat > /etc/cron.d/tallerbot-backup <<'EOF'
15 3 * * * root /usr/local/bin/tallerbot-backup
EOF

echo "== LISTO =="
echo "1. Crea el .env:  sudo nano $SITIO/.env   (token + CODIGOS_TALLER)"
echo "2. Relanza:       sudo systemctl restart tallerbot"
echo "3. Logs en vivo:  journalctl -u tallerbot -f"
