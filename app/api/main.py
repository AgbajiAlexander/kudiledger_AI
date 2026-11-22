from fastapi import FastAPI


def create_app():
    app = FastAPI(
        title="KudiLedger AI",
        description="Financial record-keeping API for Nigerian SMEs",
        version="0.1.0",
    )

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "application": "KudiLedger AI",
            "version": "0.1.0",
        }

    return app


app = create_app()
