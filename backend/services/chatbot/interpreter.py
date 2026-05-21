"""
Generates chatbot responses using LiteLLM (Groq, Gemini, local models, etc.).

If the LLM is disabled, missing, or fails, it falls back to a plain text
summary built from the context — no exceptions raised.
Main function: generate_chatbot_response()
"""
from __future__ import annotations

import json
from typing import Any, Dict

from backend.core.config import Settings

try:
    from litellm import completion
except ModuleNotFoundError:
    completion = None


def _fallback_response(question: str, context: Dict[str, Any], reason: str) -> str:
    summary = context.get("summary", {})
    alerts = summary.get("recent_alerts", 0)
    high_alerts = summary.get("high_alerts", 0)
    anomaly_windows = summary.get("anomaly_windows", 0)
    latest_status = summary.get("latest_run_status", "unknown")
    latest_risk = summary.get("latest_risk_level", "unknown")
    latest_reason = summary.get("latest_anomaly_reason", "unknown")
    fallback_counts = summary.get("fallback_pending_counts", {})

    return (
        "No pude usar un modelo LLM en este momento"
        f" ({reason}).\n\n"
        "Resumen operativo:\n"
        f"- Alertas recientes: {alerts} (alta severidad: {high_alerts})\n"
        f"- Ventanas con anomalia: {anomaly_windows}\n"
        f"- Estado ultimo ingestion run: {latest_status}\n\n"
        f"- Riesgo/anomalia mas reciente: {latest_risk} / {latest_reason}\n"
        f"- Pendientes fallback: {fallback_counts}\n\n"
        "Tip: configura LLM_PROVIDER_MODEL y LLM_API_KEY para respuestas interpretadas.\n"
        f"Pregunta recibida: {question}"
    )


def _build_messages(question: str, context: Dict[str, Any]) -> list[Dict[str, str]]:
    context_json = json.dumps(context, ensure_ascii=True, default=str)

    system_prompt = (
        "Eres un analista SOC que responde en espanol para Telegram. "
        "Usa solo el contexto entregado, especialmente endpoint_snapshots. "
        "Cuando sea util, menciona el endpoint que respalda tu conclusion. "
        "Si faltan datos, dilo claramente. "
        "Responde en maximo 8 lineas, con foco operativo y acciones concretas."
    )

    user_prompt = (
        "Pregunta del operador:\n"
        f"{question}\n\n"
        "Contexto estructurado:\n"
        f"{context_json}\n\n"
        "endpoint_snapshots contiene salidas equivalentes a endpoints HTTP utiles "
        "(health, history, status, dashboard, alerts, windows, runs y SAP health). "
        "No inventes datos fuera de esos snapshots.\n\n"
        "Entrega:\n"
        "1) Que esta pasando\n"
        "2) Riesgo actual\n"
        "3) Siguiente accion recomendada"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def generate_chatbot_response(
    question: str,
    context: Dict[str, Any],
    settings: Settings,
) -> Dict[str, Any]:
    if not settings.llm_enabled:
        return {
            "text": _fallback_response(question, context, "llm_disabled"),
            "source": "fallback",
        }

    if completion is None:
        return {
            "text": _fallback_response(question, context, "litellm_not_installed"),
            "source": "fallback",
        }

    if not settings.llm_provider_model:
        return {
            "text": _fallback_response(question, context, "missing_model_name"),
            "source": "fallback",
        }

    try:
        kwargs: Dict[str, Any] = {
            "model": settings.llm_provider_model,
            "messages": _build_messages(question, context),
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
        }
        if settings.llm_api_key:
            kwargs["api_key"] = settings.llm_api_key
        if settings.llm_base_url:
            kwargs["api_base"] = settings.llm_base_url

        response = completion(**kwargs)
        content = response.choices[0].message.content if response and response.choices else ""
        text = (content or "").strip()
        if not text:
            text = _fallback_response(question, context, "empty_llm_response")
            return {"text": text, "source": "fallback"}
        return {"text": text, "source": "llm"}
    except Exception as exc:
        return {
            "text": _fallback_response(question, context, f"llm_error: {exc}"),
            "source": "fallback",
        }
