from backend.core.config import load_settings

from html import escape

import logging
from typing import Any, Dict
import re

try:
    from aiogram import Bot, Dispatcher, Router
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.filters import Command, CommandStart
    from aiogram.types import Message
    
except ModuleNotFoundError:
    Bot = None
    Dispatcher = None
    Router = None
    DefaultBotProperties = None
    ParseMode = None
    Command = None
    Message = Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

#Config bot
logger = logging.getLogger("sap_soc_backend")

settings = load_settings()

token = settings.token_bot_telegram
bot: Bot | None = None
if Bot and DefaultBotProperties and ParseMode and token:
    try:
        bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
    except Exception as exc:
        logger.warning("Telegram bot disabled due to invalid token: %s", exc)
else:
    logger.info("Telegram bot disabled: TOKEN_BOT_TELEGRAM is not configured")

    
router = Router(name=__name__) if Router else None
dp = Dispatcher() if Dispatcher else None
if dp and router:
    dp.include_router(router)


# Messages

if router and Command:
    @router.message(Command("last_status"))
    async def last_status_telegram(message: Message):
        from backend.api.http import status_latest
        result = status_latest()
        text = str(result)
        patron = r"'([^']+)':\s*([^,}]+)"
        matches = re.findall(patron, text)
        
        lineas = []
        for clave, valor in matches:
            valor_limpio = valor.strip("'\" ")
            clave_fmt = clave.replace('_', ' ').title()
            valor_safe = valor_limpio.replace('<', '&lt;').replace('>', '&gt;')
            
            lineas.append(f"• <b>{clave_fmt}:</b> {valor_safe}")

        mensaje_final = "<b>Estado del Sistema</b>\n\n" + "\n".join(lineas)
        
        if bot is None:
            await message.answer("Telegram bot no está configurado.")
            return

        await bot.send_message(
            chat_id=message.chat.id, 
            text=mensaje_final, 
            parse_mode="HTML" 
        )

if router and Command:
    @router.message(Command("health"))
    async def health_telegram(message: Message):
        from backend.api.http import health
        if bot is None:
            await message.answer("Telegram bot no esta configurado en este entorno.")
            return
        try:
            result = await health()
            text = str(result)
            patron = r"'([^']+)':\s*([^,}]+)"
            matches = re.findall(patron, text)
            lineas = []
            for clave, valor in matches:
                valor_limpio = valor.strip("'\" ")       # ← faltaba esta línea
                lineas.append(f"• <b>{clave.replace('_', ' ').title()}... </b> {escape(valor_limpio)}")
            mensaje_final = "<b>Estado del Sistema</b>\n\n" + "\n".join(lineas)
            await bot.send_message(chat_id=message.chat.id, text=mensaje_final, parse_mode="HTML")
        except Exception as exc:
            await bot.send_message(chat_id=message.chat.id, text=f"❌ Error: {escape(str(exc))}", parse_mode="HTML")

if router and Command:
    @router.message(Command("alerts_recent"))
    async def alert_recent_telegram(message: Message):
        from backend.api.http import alerts_recent
        if bot is None:
            await message.answer("Telegram bot no esta configurado en este entorno.")
            return
        try:
            args = message.text.split()
            limit = int(args[1]) if len(args) >= 2 and args[1].isdigit() else 3

            result = alerts_recent(limit=limit)
            await bot.send_message(
                    chat_id=message.chat.id,
                    text="<b>Alertas Recientes</b>",
                    parse_mode="HTML"
            )

            for i, alert in enumerate(result, 1):
                lineas =[]
                payload = alert.get('payload', {})
                inner = payload.get('payload', {})
                
                detected = alert.get('detected_at_utc', '')[:19].replace('T', ' ')
                
                lineas.append(
                    f"<b>#{i} {alert.get('alert_type', 'N/A')}</b>\n"
                    f"  Severidad: <b>{alert.get('severity', 'N/A').upper()}</b>\n"
                    f"  Detectado: {detected}\n"
                    f"  Score: {payload.get('score', 'N/A')}\n"
                    f"  Eventos seguridad: {inner.get('security_count', 'N/A')}\n"
                    f"  Errores sistema: {inner.get('error_count', 'N/A')}\n"
                    f"  Tasa seguridad: {round(inner.get('security_event_rate', 0) * 100, 2)}%\n"
                    f"  Tasa errores: {round(inner.get('system_error_rate', 0) * 100, 2)}%\n"
                )

                await bot.send_message(
                    chat_id=message.chat.id,
                    text="\n".join(lineas),
                    parse_mode="HTML"
                )

        except Exception as exc:
            await bot.send_message(chat_id=message.chat.id, text=f"Error: Pon un rango correcto")

if router and Command:
    @router.message(Command("metrics_windows"))
    async def alert_recent_telegram(message: Message):
        from backend.api.http import metrics_windows
        if bot is None:
            await message.answer("Telegram bot no esta configurado en este entorno.")
            return
        try:
            args = message.text.split()
            limit = int(args[1]) if len(args) >= 2 and args[1].isdigit() else 3
            result = metrics_windows(limit=limit)
            
            await bot.send_message(
                chat_id=message.chat.id,
                text=f"<b>Metricas por ventana: {limit} ventanas</b>\n",
                parse_mode="HTML"
            )
            for i, window in enumerate(result, 1):
                lineas = []
                for key, value in window.items():

                    key_fmt = key.replace('_', ' ').capitalize()
                    if isinstance(value, str) and 'T' in value:
                        value_fmt = value[:19].replace('T', ' ')  
                    elif isinstance(value, float):
                        value_fmt = round(value, 4)             
                    elif value is None:
                        value_fmt = 'N/A'
                    else:
                        value_fmt = value 
                    lineas.append(f"  • <b>{key_fmt}:</b> {value_fmt}")

                lineas.append("")  

                await bot.send_message(
                    chat_id=message.chat.id,
                    text="\n".join(lineas),
                    parse_mode="HTML"
                )
        except Exception as exc:
            await bot.send_message(chat_id=message.chat.id, text=f"Error: Pon un rango correcto")

if router and Command:
    @router.message(Command("runs_recent"))
    async def run_recent_telegram(message: Message):
        from backend.api.http import runs_recent
        if bot is None:
            await message.answer("Telegram bot no esta configurado en este entorno.")
            return
        
        try:
            args = message.text.split()
            limit = int(args[1]) if len(args) >= 2 and args[1].isdigit() else 3
            result = runs_recent(limit=limit)

            await bot.send_message(
                chat_id=message.chat.id,
                text=f"<b>Historial reciente: {limit} ingestiones</b>\n",
                parse_mode="HTML"
            )
            for i, run in enumerate(result,1):
                lineas =[]
                for key, value in run.items():
                    key_fmt = key.replace('_', ' ').capitalize()
                    if isinstance(value, str) and 'T' in value:
                        value_fmt = value[:19].replace('T', ' ')  
                    elif isinstance(value, float):
                        value_fmt = round(value, 4)             
                    elif value is None:
                        value_fmt = 'N/A'
                    else:
                        value_fmt = value 
                    lineas.append(f"  • <b>{key_fmt}:</b> {value_fmt}")
                lineas.append("")  

                await bot.send_message(
                    chat_id=message.chat.id,
                    text="\n".join(lineas),
                    parse_mode="HTML"
                )
        except Exception as exc:
            await bot.send_message(chat_id=message.chat.id, text=f"Error: Pon un rango correcto")


if router and Command:
    @router.message(Command("dashboard"))
    async def dashboard_telegram(message: Message):
        from backend.api.http import dashboard_summary

        if bot is None:
            await message.answer("Telegram bot no esta configurado en este entorno.")
            return

        args = message.text.split()
        limit = int(args[1]) if len(args) >= 2 and args[1].isdigit() else 24

        try:
            result = dashboard_summary(time_window_hours=limit)
            m = result.get("top_metrics", {})
            alerts = result.get("alerts_by_severity", {})
            total_alerts = result.get("total_alerts", 0)
            last_run = result.get("last_run", {})

            w_start = (m.get("window_start", "")[:19] or "").replace("T", " ")
            w_end   = (m.get("window_end",   "")[:19] or "").replace("T", " ")
            risk    = m.get("risk_level", "N/A").upper()
            threat  = m.get("threat_score", "N/A")

            risk_icon = {"SUSPICIOUS": "⚠️", "HIGH": "🔴", "LOW": "🟢", "MEDIUM": "🟡"}.get(risk, "ℹ️")

            lines = [
                f"<b>Security Dashboard</b>",
                f"<b>Rango de tiempo: {limit} horas</b>\n"
                f"<b>{w_start} → {w_end} UTC</b>",
                f"{risk_icon} Nivel de riesgo: <b>{risk}</b>   |   Threat score: <b>{threat}/10</b>",
                "",
                
                f"<b>Alertas ({total_alerts} total)</b>",
                f"  🔴 Alta:   <b>{alerts.get('high', 0)}</b>",
                f"  🟡 Media:  <b>{alerts.get('medium', 0)}</b>",
                f"  🟢 Baja:   <b>{alerts.get('low', 0)}</b>",
                "",
                # ── Volumen ───────────────────────────────────
                f"📦 <b>Volumen</b>",
                f"  • Registros totales: <b>{m.get('total_records', 0):,}</b>",
                f"  • IPs únicas:  <b>{m.get('unique_client_ips', 0)}</b>",
                f"  • Servicios: <b>{m.get('unique_services', 0)}</b>",
                "",
                # ── LLM ───────────────────────────────────────
                f"🤖 <b>LLM</b>",
                f"  • Solicitudes:   <b>{m.get('llm_request_count', 0):,}</b>",
                f"  • Error rate:    <b>{round(m.get('llm_error_rate', 0) * 100, 1)}%</b>  ({m.get('llm_error_count', 0)} errores)",
                f"  • Timeout rate:  <b>{round(m.get('llm_timeout_rate', 0) * 100, 1)}%</b>  ({m.get('llm_timeout_count', 0)} timeouts)",
                f"  • Latencia avg:  <b>{round(m.get('avg_llm_latency_ms', 0)):,} ms</b>",
                f"  • Latencia p95:  <b>{round(m.get('p95_llm_latency_ms', 0)):,} ms</b>",
                f"  • Costo total:   <b>${round(m.get('total_llm_cost_usd', 0), 2)}</b>",
                "",
                f"🌐 <b>HTTP Errors</b>",
                f"  • 4xx: <b>{m.get('http_4xx_count', 0)}</b>",
                f"  • 5xx: <b>{m.get('http_5xx_count', 0)}</b>",
                "",
                f"🔍 <b>Anomalía</b>",
                f"  • Detectada:  <b>{'Sí' if m.get('is_anomaly') else 'No'}</b>",
                f"  • Razón:      <b>{m.get('anomaly_reason', 'N/A')}</b>",
                f"  • Score:      <b>{m.get('anomaly_score', 0)}</b>",
                "",
                f"⚙️ <b>Última ejecución</b>",
                f"  • Estado:    <b>{last_run.get('status', 'N/A')}</b>",
                f"  • Duración:  <b>{round(last_run.get('duration_seconds', 0), 2)} s</b>",
            ]

            await bot.send_message(
                chat_id=message.chat.id,
                text="\n".join(lines),
                parse_mode="HTML"
            )

        except ValueError:
            await bot.send_message(
                chat_id=message.chat.id,
                text="Error: Usa un número de horas válido. Ejemplo: /dashboard 24"
            )
        except Exception as exc:
            await bot.send_message(
                chat_id=message.chat.id,
                text=f"Error inesperado: {exc}"
            )

if router and Command:
    @router.message(CommandStart())
    async def start(message: Message):
        if bot is None:
            await message.answer("Telegram bot no está configurado.")
            return

        lines = [
            "👋 <b>Hola, soy Perritos Assistant</b>",
            "Mi función es notificarte que el sistema funciona correctamente.",
            "",
            "📖 <b>Comandos disponibles</b>",
            "",
            "🏥 <b>Health</b>",
            "  <code>/health</code>  —  Salud del servidor",
            "",
            "📋 <b>Último estado</b>",
            "  <code>/last_status</code>  —  Último estado de recolección",
            "",
            "🚨 <b>Alertas recientes</b>",
            "  <code>/alerts_recent [n]</code>  —  Últimas N alertas  <i>(default 3)</i>",
            "",
            "📈 <b>Métricas por ventana</b>",
            "  <code>/metrics_windows [n]</code>  —  Últimas N ventanas  <i>(default 3)</i>",
            "",
            "🗂  <b>Historial de runs</b>",
            "  <code>/runs_recent [n]</code>  —  Últimas N ingestiones  <i>(default 3)</i>",
            "",
            "📊 <b>Dashboard</b>",
            "  <code>/dashboard [h]</code>  —  Resumen de las últimas H horas  <i>(default 24)</i>",
        ]

        await bot.send_message(
            chat_id=message.chat.id,
            text="\n".join(lines),
            parse_mode="HTML"
        )
        
if router and Command:
    @router.message(Command("ask"))
    async def ask_telegram(message: Message) -> None:
        from backend.api.http import _extract_command_argument, _handle_telegram_analysis

        raw_text = (message.text or "").strip()
        question = _extract_command_argument(raw_text, "ask")
        await _handle_telegram_analysis(message, question)

    @router.message()
    async def free_text_telegram(message: Message) -> None:
        from backend.api.http import  _handle_telegram_analysis
        raw_text = (message.text or "").strip()
        if not raw_text or raw_text.startswith("/"):
            return
        await _handle_telegram_analysis(message, raw_text)


async def run_bot() -> None:
    if dp is not None and bot is not None:
        await dp.start_polling(bot)