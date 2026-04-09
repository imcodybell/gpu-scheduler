"""FastAPI entry point for the GPU Scheduler Platform."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from scheduler import scheduler
from routers import gpus, instances, telemetry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(__: FastAPI):
    logger.info("Initializing database tables...")
    init_db()
    logger.info("Starting scheduler background tasks...")
    scheduler.start_background_tasks()
    yield


app = FastAPI(title="GPU Scheduler", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"service": "GPU Scheduler", "version": "0.1.0"}


# Register routers
app.include_router(gpus.router)
app.include_router(instances.router)
app.include_router(telemetry.router)
