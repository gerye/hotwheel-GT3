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

# 注意顺序:更具体的 /static/uploads 必须挂在 /static 之前,
# 否则 /static 会作为前缀先命中,把上传图片请求劫走导致 404。
app.mount("/static/uploads", StaticFiles(directory=config.IMAGES_DIR),
          name="uploads")
app.mount("/static", StaticFiles(directory=config.BASE_DIR / "app" / "static"),
          name="static")


@app.get("/")
def home() -> RedirectResponse:
    return RedirectResponse(url="/database")


from app.routers import pages, cars, teams, seasons, races, standings  # noqa: E402
app.include_router(pages.router)
app.include_router(cars.router)
app.include_router(teams.router)
app.include_router(seasons.router)
app.include_router(races.router)
app.include_router(standings.router)
