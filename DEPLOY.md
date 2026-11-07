# 🚀 DEPLOY — TallerBot en Oracle Always Free (24/7, $0)

Guía para dejar el bot corriendo **siempre** en una VM gratuita de Oracle Cloud.
No hay nada que abrir al mundo: el bot usa *long polling* (solo sale a Telegram), así que el
firewall queda con únicamente SSH abierto. La BD (`taller.db`) vive en el disco de la VM:
**no se pierde en reinicios**.

---

## 0. Pre-requisito: subir el código a GitHub

Oracle solo importa el código desde GitHub. Si tienes commits locales pendientes:

```bash
git push origin main
```

---

## 1. Crear la cuenta y la VM en Oracle Cloud

1. Entra a [cloud.oracle.com](https://cloud.oracle.com) y crea una cuenta **Free Tier**
   (pide tarjeta solo para verificar identidad; no cobra en el plan Always Free).
2. Elige una **región** cercana (Colombia: `us-ashburn-1` o `sa-saopaulo-1`).
3. Menú ☰ → **Compute → Instances → Create Instance**:
   - **Name**: `tallerbot`
   - **Image**: `Canonical Ubuntu 22.04` (o 24.04)
   - **Shape**: `VM.Standard.A1.Flex` (Ampere ARM) → 2 OCPU / 12 GB RAM *(Always Free: hasta 4 OCPU / 24 GB en total)*
   - **SSH keys**: pega tu clave pública o deja que Oracle te descargue la privada (`.key`)
4. **Create**. En ~1 minuto la instancia queda `RUNNING` — copia su **IP pública**.

> ⚠️ Si el shape sale "out of capacity" en tu región, prueba shape `VM.Standard.E2.1.Micro` (1 GB RAM, también Always Free; el setup.sh le crea swap automáticamente).

---

## 2. Conectar y subir el código

```bash
# Desde tu PC (PowerShell) — conectar por SSH:
ssh -i ruta_de_tu_clave ubuntu@IP_PUBLICA

# Copia del repo (si es privado, mete tu token de GitHub en la URL):
sudo git clone https://TU_TOKEN@github.com/dzuluaga23/TallerBot.git /opt/tallerbot
sudo chown -R ubuntu:ubuntu /opt/tallerbot
```

**¿Tenías datos en tu PC?** Migra la BD y los logos ANTES de correr setup.sh:

```bash
# En tu PC (PowerShell), con la IP de la VM:
scp taller.db logos/*.jpg ubuntu@IP_PUBLICA:/home/ubuntu/
# De vuelta en la VM:
sudo mv /home/ubuntu/taller.db /home/ubuntu/*.jpg /opt/tallerbot/
# (los logos se renombran así: mv /opt/tallerbot/taller_N.jpg /opt/tallerbot/logos/taller_N.jpg
#  si la carpeta logos/ no existe: sudo mkdir /opt/tallerbot/logos)
```

---

## 3. Setup automático (todo lo demás)

```bash
cd /opt/tallerbot
sudo bash deploy/setup.sh
```

El script instala Python/venv/sqlite3, crea el usuario del servicio, el servidor de swap si hace
falta, el firewall (solo SSH), el servicio systemd y el cron de backup diario.

## 4. El `.env` en el servidor

Con tus datos de verdad (el token del mismo bot, tus códigos de venta):

```bash
sudo nano /opt/tallerbot/.env      # pegar:
# TELEGRAM_TOKEN=...
# CODIGOS_TALLER=VENTA-...
sudo chmod 600 /opt/tallerbot/.env
sudo systemctl restart tallerbot
```

## 5. Verificar y operar

```bash
systemctl status tallerbot      # debe decir active (running)
journalctl -u tallerbot -f      # logs en vivo (Ctrl+C para salir)
```

Y en Telegram: pídele al bot `/ayuda`. Responde = está vivo.

| Tarea | Comando |
|---|---|
| Reiniciar | `sudo systemctl restart tallerbot` |
| Ver errores | `journalctl -u tallerbot --since "1 hour ago"` |
| Actualizar código | `cd /opt/tallerbot && sudo -u ubuntu git pull && sudo chown -R tallerbot:tallerbot . && sudo systemctl restart tallerbot` |
| Backup a mano | `sudo /usr/local/bin/tallerbot-backup` |
| Restaurar backup | `sudo systemctl stop tallerbot && sudo cp /var/backups/tallerbot/taller-FECHA.db /opt/tallerbot/taller.db && sudo systemctl start tallerbot` |

El **backup automático** corre todos los días a las 03:15 (14 copias rotativas en
`/var/backups/tallerbot/`). La BD también sigue viva en su disco normal; los backups son
seguro ante corrupción o error humano.

---

## 6. Apagar el bot local

Solo puede haber un proceso con el token: deja de correr `venv\Scripts\python bot.py` en tu PC
(si lo tienes en "autoinicio", saca esa tarea). La PC agendada ahora es redundante.

## 7. Pilotaje de 48 h

- ✅ Día 1: mandar `/ayuda`, registrar un trabajo de prueba, verificar en la BD desde la VM con `sqlite3 /opt/tallerbot/taller.db "SELECT COUNT(*) FROM trabajos;"`
- ✅ Día 2: `uptime 14` en la VM, `systemctl status tallerbot` (que no haya restarts raros), y `/factura` de una placa real para ver el PDF generado en la nube.
- ✅ Después: apaga tu PC una noche entera — el bot debe contestar igual.

---

## Cómo se paga esto 💰

Plan **Always Free**: la VM Ampere (2 OCPU / 12 GB) y su disco de boot entran en el cupo gratis
**permanente** (no es prueba de 30 días). Cuidados:

- NO subas el shape a formas de pago por accidente (el panel te lo propone).
- Si un día Oracle te manda mail "reclaim of idle instances", es para VM micro (E2.1) —
  la Ampere con CPU usada por el bot no cae en esa regla.
