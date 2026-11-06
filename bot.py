"""Bot del taller - Sprint 1: registro de trabajos.

El mecanico envia un mensaje tipo:
    ABC123 cambio de aceite 45000
y el bot lo guarda en la base de datos y confirma con una ficha.
Comandos: /start (prueba de vida). Los reportes llegan en el Sprint 2.
"""
import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from parser import (
    MOTIVO_DESCRIPCION,
    MOTIVO_PLACA,
    MOTIVO_PRECIO,
    MOTIVO_VACIO,
    MOTIVO_VARIAS_PLACAS,
    ParserError,
    parse,
)
import db

# Carga las variables del archivo .env (token, ids autorizados, etc.)
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Configura los logs: latido de cada mensaje y errores visibles
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # silencia el ruido de red
logger = logging.getLogger("taller-bot")

# Respuestas cuando el parser no entiende el mensaje (ticket S1-4)
MENSAJES_DE_ERROR = {
    MOTIVO_VACIO: "Wrote something, I'm listening 👀",
    MOTIVO_PLACA: (
        "No encontré la placa 🤔\n"
        "Agregué la placa del vehículo al mensaje.\n"
        "Ejemplos: <code>ABC123 cambio de aceite 45000</code> (carro) "
        "o <code>KGH12D cambio de tiras 38000</code> (moto)"
    ),
    MOTIVO_PRECIO: (
        "No encontré el precio 🤔\n"
        "Termina el mensaje con un valor.\n"
        "Ejemplo: <code>ABC123 cambio de aceite 45000</code>"
    ),
    MOTIVO_DESCRIPCION: (
        "No encontré el trabajo 🤔\n"
        "Soy un chatbot: necesito la placa, el trabajo y el precio.\n"
        "Ejemplo: <code>ABC123 cambio de aceite 45000</code>"
    ),
    MOTIVO_VARIAS_PLACAS: (
        "Encontré varias placas 🤔\n"
        "Deja solo la placa del vehículo que atendiste.\n"
        "Ejemplo: <code>ABC123 cambio de aceite 45000</code>"
    ),
}


def formatear_dinero(valor: float) -> str:
    """45000.0 -> '$45.000' con separador de miles estilo Colombia."""
    return f"$ {valor:,.0f}".replace(",", ".")


def formatear_fecha(mensaje_dt: datetime) -> str:
    """16/11/2026 2:45 p.m."""
    return mensaje_dt.strftime("%d/%m/%Y %I:%M %p").lower()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respuesta al comando /start."""
    await update.message.reply_text(
        "¡Hola! 🛠️ Soy el bot del taller.\n\n"
        "Para registrar un trabajo, mándame un solo mensaje con:\n"
        "<b>placa + trabajo + precio</b>\n"
        "Ejemplo: <code>ABC123 cambio de aceite 45000</code>\n\n"
        "Mándalo así como esté: con $, con separadores y la placa "
        "al final también me sirven 😉"
    )
    logger.info("/start de %s", update.effective_user.username)


async def registrar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Guarda un trabajo desde un mensaje normal (no comando)."""
    texto = update.message.text
    try:
        resultado = parse(texto)
    except ParserError as error:
        await update.message.reply_text(
            MENSAJES_DE_ERROR.get(error.motivo, MENSAJES_DE_ERROR[MOTIVO_VACIO]),
            parse_mode="HTML",
        )
        return

    trabajo_id = db.agregar_trabajo(
        placa=resultado.placa,
        descripcion=resultado.descripcion,
        precio=resultado.precio,
        chat_id=update.effective_chat.id,
    )
    await update.message.reply_text(
        f"✅ <b>Trabajo #{trabajo_id} registrado</b>\n"
        f"🛻️ Placa: <b>{resultado.placa}</b>\n"
        f"🔧 Trabajo: {resultado.descripcion}\n"
        f"💰 Valor: {formatear_dinero(resultado.precio)}\n"
        f"🕒 {formatear_fecha(datetime.now())}"
    )
    logger.info(
        "Trabajo #%s: %s %s %.0f", trabajo_id, resultado.placa, resultado.descripcion, resultado.precio
    )


def main() -> None:
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "aqui_va_el_token":
        raise SystemExit(
            "Falta el token. Copia .env.example como .env y pega tu token de @BotFather."
        )
    db.init_db()  # crea taller.db si no existe

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    # Todo texto que no sea comando es un registro (ticket S1-3)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, registrar))

    logger.info("Bot iniciado. Presiona Ctrl+C para detener.")
    app.run_polling()  # long polling: sin dominio ni certificados


if __name__ == "__main__":
    main()
