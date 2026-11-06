# 🛠️ TallerBot

Bot de Telegram para talleres de mecánica: los mecánicos registran sus trabajos mandando un mensaje corto, y el dueño consulta ganancias e historiales con comandos. Pensado para manos ocupadas: todo se hace desde el chat, sin apps ni formularios.

## 🚀 Inicio rápido

```bash
# 1. Instalar dependencias
py -m venv venv
venv\Scripts\python -m pip install -r requirements.txt

# 2. Configurar
#    Copia .env.example como .env y llena tu token (de @BotFather)
#    y tu ID (de @userinfobot) en ADMIN_IDS.

# 3. Correr
venv\Scripts\python bot.py

# 4. Probar
venv\Scripts\python -m pytest tests -v
```

## 📱 Uso diario

**Registrar un trabajo** — solo manda el mensaje (formato flexible: `$`, `.`, `,`, placa al final, mayúsculas/minúsculas da igual):

```
ABC123 cambio de aceite 45000
```

| Comando | Dueño | Mecánico |
|---|---|---|
| `/historialdia` | Todos los trabajos de hoy + total | Solo los suyos |
| `/ganancias 7` · `/ganancias mes` | Total del taller + desglose por mecánico | Solo sus sumas |
| `/misganancias` | Sus propias cifras | Sus propias cifras |
| `/buscar ABC123` | Historial completo del vehículo | Solo sus registros |
| `/borrar 5` | Cualquier registro | Solo los suyos |
| `/exportar mes` (CSV) | ✅ Solo el dueño | ❌ |
| `/ayuda` | Menú de comandos | Menú de comandos |

## ⚙️ Configuración (`.env`)

```ini
TELEGRAM_TOKEN=...      # de @BotFather
ADMIN_IDS=111:Duque     # dueño(s): ven todo. Varios: separados por coma
MECHANICS=222:Pedro,333:Juan   # cada uno SOLO ve lo suyo
```

IDs nuevos: la persona escribe a `@userinfobot` → copias su Id → agregas la línea → reinicia el bot.

## 🗄️ Base de datos — `taller.db` (SQLite, un solo archivo)

Tabla `trabajos`:

| Columna | Qué guarda |
|---|---|
| `id` | Número del registro (para `/borrar`) |
| `fecha_hora` | Fecha y hora ISO: 2026-11-07T14:05:32 |
| `placa` | MAYÚSCULAS. Carro: ABC123 · Moto: ABC12D |
| `descripcion` | Trabajo realizado |
| `precio` | Valor cobrado (REAL) |
| `chat_id` | Chat de Telegram donde se registró |
| `anulado` | 0 = activo, 1 = borrado lógico (la info nunca se destruye) |
| `usuario_id` | Telegram de quien registró |
| `mecanico` | Nombre firmado |

Herramientas para abrirla: **DB Browser for SQLite** (gratis). Respaldo: copia el archivo.

## 📂 Estructura del proyecto

```
TallerBot/
├── bot.py       # punto de entrada: comandos, roles y respuestas
├── parser.py    # interpreta mensajes de registro (placa/trabajo/precio)
├── db.py        # SQLite: guardar, consultas, filtros por rol
├── roles.py     # ADMIN_IDS / MECHANICS leídos del .env
├── tests/       # 34 tests (parser, BD, acceso, formato)
├── taller.db    # datos (se crea sola; NO se sube a GitHub)
├── .env         # token y roles (NUNCA subir a GitHub)
└── taller-bot.log  # logs rotativos
```

## 🏗️ Arquitectura rápida

`Telegram (long polling)` → `bot.py` decide por rol → `parser.py` valida el mensaje → `db.py` guarda/lee → `responder()` contesta con HTML enriquecido.

## 🧰 Tecnologías utilizadas

| Categoría | Tecnología | Para qué |
|---|---|---|
| Lenguaje | **Python 3.14** | Todo el proyecto |
| Framework bot | **python-telegram-bot 22.8** | Conexión con Telegram (long polling, handlers, callbacks) |
| Base de datos | **SQLite 3** (módulo `sqlite3` de la librería estándar) | Un solo archivo `taller.db`, sin servidor de BD |
| Configuración | **python-dotenv** | Variables secretas (token, roles) en `.env` |
| Testing | **pytest** | 34 tests unitarios y de integración |
| Control de versiones | **Git + GitHub** | Historial del código |
| Producto | **Telegram Bot API** | La "interfaz" con la que trabajan los mecánicos (0 costo) |

## 🧠 Ingeniería de software aplicada

Decisiones y prácticas de este proyecto más allá del código:

- **Separación de responsabilidades ([SoC](https://en.wikipedia.org/wiki/Separation_of_concerns)):** cada módulo hace una sola cosa (parser ≠ base de datos ≠ roles ≠ respuestas). Cambiar el formato de los mensajes NO toca SQL.
- **Control de acceso en profundidad (defensa en capas):** primero el decorador `protegido` (lista blanca en `roles.py`), después reglas por rol dentro de cada comando, y `/borrar` re-verifica contra la BD en el callback. Tres capas, no una.
- **Borrado lógico (soft delete):** ningún registro se destruye; `/borrar` solo marca `anulado=1`. Trazabilidad para auditorías y errores humanos.
- **Migraciones simples idempotentes:** `db.init_db()` crea tablas y agrega columnas nuevas con `ALTER TABLE` silencioso si ya existen. La BD vieja del Sprint 1 vive sin romper.
- **Fail-safe en superficie:** `error_global` captura toda excepción, loguea y responde algo amable — *ningún handler tumba al bot*. Nunca silencio: hasta los comandos mal escritos (`/ganancia` sin `s`) tienen alias y un fallback.
- **Configuración fuera del código (12-factor "config"):** roles y secretos en `.env`, no constantes quemadas. Cambiar el dueño o agregar un mecánico no toca una línea de código ni requiere redeploy.
- **Un solo canal de respuestas:** toda salida pasa por `responder()` con `parse_mode="HTML"` — imposible que un mensaje nuevo repita el bug del `<b>` literal.
- **Testing primero donde importa:** el parser (la parte que usan manos ocupadas) y las reglas de visibilidad por rol tienen cobertura de tests; la BD se prueba con archivos temporales `tmp_path` para no tocar datos reales.
- **Git con disciplina:** commits por sprint con tickets (S5-2, S5-3…), `.gitignore` excluyendo secretos (`.env`) y datos (`*.db`, `*.log`).

## 📖 Sprints del proyecto

0. ✅ Esqueleto y setup · 1. ✅ Registro de trabajos · 2. ✅ Comandos de consulta · 3. ✅ Seguridad (lista blanca + logs) · 5. ✅ Roles dueño/mecánico + firma · 4. ⬜ Nube gratuita (despliegue 24/7)
