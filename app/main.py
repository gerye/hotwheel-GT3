from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from app import config, db

app = FastAPI(title="风火轮 GT3")


@app.on_event("startup")
def _startup() -> None:
    config.ensure_dirs()
    db.init_db()


config.ensure_dirs()

app.mount("/static", StaticFiles(directory=config.BASE_DIR / "app" / "static"),
          name="static")
app.mount("/static/uploads", StaticFiles(directory=config.IMAGES_DIR),
          name="uploads")


@app.get("/")
def home() -> RedirectResponse:
    return RedirectResponse(url="/database")


from app.routers import pages, cars, teams, seasons, races  # noqa: E402
app.include_router(pages.router)
app.include_router(cars.router)
app.include_router(teams.router)
app.include_router(seasons.router)
app.include_router(races.router)
