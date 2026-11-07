# 🚀 DEPLOY — TallerBot en Render (24/7, $0)

Guía para dejar el bot corriendo siempre en la nube gratis con [Render](https://render.com).
El bot usa *long polling*: no abre nada al mundo; Render solo le pide responder HTTP en su
puerto interno (y eso ya lo hace el bot con su endpoint `/salud`).

## ⚠️ La regla de Render free (y cómo la resolvimos)

| Limitación | Cómo la resolvimos |
|---|---|
| Sin disco persistente: en cada restart/se borra `taller.db` | `respaldo.py` sube la BD a un **repo privado de GitHub** cada 10 min y la **restaura al arrancar** si falta |
| Duerme tras ~15 min sin tráfico | Un pinger externo gratuito (cron-job.org) le pega a la URL cada 10 min |

Ventana de pérdida teórica: si el proceso muriera en medio de un intervalo, se pierde lo
registrado desde el último respaldo (máximo ~10 min). En una VM con disco (Oracle) el precio
es cero: si algún día un taller te exige cero pérdida, la migración es solo copiar el mismo
`taller.db` a otra infraestructura — nada del código cambia.

Cupo gratuito: una cuenta Render free da ~750 horas/mes corriendo — **exactamente una app
24/7**. No crees otros servicios free en la misma cuenta o se reparten el cupo.

## 0. Pre-requisito: subir el código a GitHub

```bash
git push origin main
```

## 1. Crea el repo de respaldo y su token

1. En GitHub: **New repository** → nombre `respaldo-taller` → **Private**.
2. Crea un token: GitHub → Settings → Developer settings → **Fine-grained token**:
   - **Repository access**: solo `respaldo-taller`
   - **Permissions**: Contents → **Read and write**
   - Copia el token (`github_pat_...`) — solo se ve una vez.

## 2. Crea el Web Service en Render

1. [dashboard.render.com](https://dashboard.render.com) → **New + → Web Service**.
2. Conecta tu GitHub y elige el repo `TallerBot`.
3. Con `render.yaml` incluido, casi todo viene lleno, pero confirma:
   - **Runtime**: Python 3 · **Build**: `pip install -r requirements.txt`
   - **Start**: `python bot.py` · **Plan**: Free
4. **Environment Variables** (Render rellena las de `sync: false`):

| Key | Valor |
|---|---|
| `TELEGRAM_TOKEN` | tu token de @BotFather |
| `CODIGOS_TALLER` | `VENTA-...` (los códigos de venta, separados por coma) |
| `GITHUB_RES_REPO` | `dzuluaga23/respaldo-taller` |
| `GITHUB_TOKEN` | el token del paso 1 |
| `RESPALDO_MINUTOS` | `10` |
| `TZ` | `America/Bogota` (hora del taller: sin eso "hoy"/"mes" corren en UTC y los reportes salen corridos) |

5. **Create Web Service**. En el Logs verás el arranque: "Servidor de salud ... (Render)",
   "Respaldos a GitHub activos" y "Bot iniciado".

## 3. Migrar la BD que ya tienes (Taller Prueba)

En Render la BD nace vacía y se restaurará del repo de respaldo. Para llevar tus datos:

1. Entra a `respaldo-taller` en GitHub → **Add file → Upload files**.
2. En el campo de nombre escribe la ruta completa: `respaldo/taller.db` (GitHub crea la carpeta).
   Sube TU `taller.db` local ahí. Commit.
3. Reinicia el servicio (Manual Deploy → Restart) — al arrancar la baja y lista,
   con talleres, usuarios y trabajos intactos.

> Logos: al no ser parte de la BD se pierden en un restart — re-súbelos una vez desde
> Telegram con `/logo` (menos de un minuto) y listo.

## 4. Que no se duerma (pinger externo)

1. Crea una cuenta en [cron-job.org](https://cron-job.org) → **Cronjobs → Create**:
   - **URL**: `https://tallerbot.onrender.com/salud` (tu URL de Render + `/salud`)
   - **Every 10 minutes**
2. Actívalo. Listo: Render ve tráfico y el servicio no duerme nunca.

## 5. Verificar y operar

| Qué revisar | Dónde |
|---|---|
| Logs en vivo | Dashboard → Events/Logs |
| Endpoint vivo | `https://tallerbot.onrender.com/salud` → `tallerbot vivo` |
| Respaldo más reciente | Repo `respaldo-taller`, commits cada ~10 min |
| Bot vivo | Telegram: `/ayuda` |

**Apagar el bot de tu PC**: solo un proceso puede usar el token — si la nube toma turno,
deja de correr `bot.py` localmente (o da error de conflicto de Telegram).

## 6. Pilotaje de 48 h

- ✅ Día 1: registra un trabajo de prueba desde Telegram, confirma que a los ~10 min aparece un commit nuevo en `respaldo-taller`.
- ✅ Día 2: Manual Deploy → **Restart** y comprueba que la BD sobrevivió (los datos de ayer siguen ahí).
- ✅ Apaga tu PC una noche entera — el bot debe contestar igual.

## 7. Solución de problemas (lo que aprendimos en vivo)

| Síntoma en los logs | Qué es | Arreglo |
|---|---|---|
| `Conflict: terminated by other getUpdates` | Dos instancias pidiendo mensajes a la vez. Normal y **transitorio** durante un deploy (la vieja se despide mientras la nueva arranca). También sale si el bot sigue corriendo en tu PC | Espera 1-2 min (se apaga solo). Si persiste: Suspension/Resume del servicio; nunca corras `bot.py` local con el mismo token que la nube |
| `Respaldos: subir fallo (HTTP 403) "Resource not accessible by personal access token"` | El token fine-grained no tiene permisos de escritura | Token → Repository permissions → **Contents: Read and write**, solo sobre el repo de respaldo |
| Arranca con `Talleres: 0` tras un deploy | La restauración no corrió (token sin permiso o sin respaldo aún) | Arregla el token → Manual Deploy → Restart → debe decir `BD restaurada desde GitHub` + `Talleres: 1` |
| Los reportes "hoy"/"mes" salen corridos en horas | El servidor vive en hora UTC | Environment → Key `TZ` = `America/Bogota` → Save |
| El bot deja de responder al rato | Plan free: siesta tras ~15 min sin tráfico | Pinger externo a `/salud` cada 10 min (cron-job.org) |
