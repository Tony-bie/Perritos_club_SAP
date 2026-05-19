"""HTTP application and route composition."""

from .application import health, status_latest, alerts_recent, metrics_windows, runs_recent, dashboard_summary, _extract_command_argument, _handle_telegram_analysis