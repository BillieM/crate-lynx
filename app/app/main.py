from fastapi import FastAPI


app = FastAPI(title="crate-lynx")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
