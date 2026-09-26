from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import get_settings

app = FastAPI(title="Prospect API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Health(BaseModel):
    status: str


@app.get("/health")
def health() -> Health:
    # Liveness only: must stay cheap (ARCHITECTURE §9).
    return Health(status="ok")
