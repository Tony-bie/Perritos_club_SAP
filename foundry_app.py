from __future__ import annotations

from flask import Flask, request

from soc_pipeline.application.pipeline import run_once
from soc_pipeline.application.training import run_training
from soc_pipeline.infrastructure.config import build_parser, load_runtime_config

app = Flask(__name__)


def runtime_config():
    parser = build_parser()
    args = parser.parse_args(["once"])
    return load_runtime_config(args)


@app.get("/")
def index():
    config = runtime_config()
    return {
        "status": "ok",
        "app": "sap-soc-pipeline",
        "mode": "web",
        "routes": {
            "health": "/health",
            "ingest_current": "/ingest/current",
            "train": "/train",
        },
        "hana_configured": config.hana_config is not None,
    }, 200


@app.get("/health")
def health():
    return {"status": "ok"}, 200


@app.post("/ingest/current")
def ingest_current():
    config = runtime_config()
    force = bool(request.args.get("force", "false").lower() in {"1", "true", "yes"})
    run_once(config=config, force=force)
    return {"status": "ok", "operation": "ingest"}, 200


@app.post("/train")
def train_model():
    config = runtime_config()
    run_training(config=config)
    return {"status": "ok", "operation": "train"}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
