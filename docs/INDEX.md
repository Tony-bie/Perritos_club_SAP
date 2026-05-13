# Índice de Documentación

Usa esta guía para encontrar rápidamente el documento correcto.

---

## Quiero entender el sistema

Lee [ARCHITECTURE.md](ARCHITECTURE.md).

Incluye:

- Problema que resuelve el sistema.
- Flujo end-to-end.
- Componentes principales.
- Diferencia entre reglas, línea base histórica y modelo.
- SQLite como fallback/respaldo cuando HANA falla.
- Rutas operativas y de administración.

Tiempo estimado: 10 a 15 minutos.

---

## Quiero instalarlo y correrlo

Lee [SETUP_GUIDE.md](SETUP_GUIDE.md).

Incluye:

- Requisitos.
- Entorno virtual.
- Variables `.env`.
- Ejecución local con SQLite.
- Ejecución con SAP HANA Cloud.
- Telegram/chatbot.
- Solución de problemas.

Tiempo estimado: 10 minutos para local; 15 a 30 minutos con HANA.

---

## Quiero verlo funcionando rápido

Ejecuta la demo local:

```bash
python tools/walkthrough_demo.py
```

Muestra:

- Carga de configuración.
- Datos simulados.
- Normalización y features.
- Scoring de riesgo.
- Alertas.
- Consultas tipo tablero.
- Limpieza por retención.

---

## Quiero revisar si está sano

Comandos útiles:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/history/status
curl http://localhost:8000/status/latest
```

Pruebas:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## Quiero desplegar con HANA Cloud

Lee [SETUP_GUIDE.md](SETUP_GUIDE.md#configuración-con-sap-hana-cloud).

Pasos generales:

1. Obtener credenciales HANA desde SAP BTP.
2. Configurar `.env` o variables de entorno.
3. Ejecutar `python tools/run_hana_migrations.py`.
4. Validar con `python tools/check_hana_ingestion.py`.
5. Levantar API y revisar `/health`.

---

## Algo se rompió

Revisa en este orden:

1. `/health` para almacenamiento, proceso en segundo plano y fallback SQLite.
2. `/history/status` para línea base/modelo.
3. `/status/latest` para última ejecución y última ventana.
4. Registros de terminal o SAP BTP Cloud Foundry.
5. Sección de solución de problemas en [SETUP_GUIDE.md](SETUP_GUIDE.md#solución-de-problemas).

Si el historial aparece en 1 aunque hay registros, corre:

```bash
curl -X POST "http://localhost:8000/run/rebuild-windows-from-raw?limit=0&persist=true" \
  -H "X-API-Key: $ADMIN_API_KEY"
```

---

## Referencia Rápida

| Pregunta | Documento/comando |
|----------|-------------------|
| Qué hace esto? | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Cómo lo instalo? | [SETUP_GUIDE.md](SETUP_GUIDE.md) |
| Cómo veo si funciona? | `curl /health`, `curl /history/status` |
| Cómo reconstruyo historial? | `POST /run/rebuild-windows-from-raw` |
| Cómo corro pruebas? | `python -m unittest discover -s tests` |
| Cómo veo una demo? | `python tools/walkthrough_demo.py` |
