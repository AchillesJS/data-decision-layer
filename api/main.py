from fastapi import FastAPI

app = FastAPI(title="Decision Workspace")

@app.get("/health")
def health():
    return {"status": "ok"}
