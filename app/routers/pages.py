from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from app import config
from app.db import get_session
from app.models import Team
from app.enums import Category
from app.services import search as ssvc

router = APIRouter()
templates = Jinja2Templates(directory=config.BASE_DIR / "app" / "templates")


def _team_names(session: Session) -> dict[int, str]:
    return {t.id: t.name for t in session.exec(select(Team)).all()}


def _team_car_counts(session: Session) -> dict[int, int]:
    from app.models import Car
    counts: dict[int, int] = {}
    for c in session.exec(select(Car)).all():
        if c.team_id is not None:
            counts[c.team_id] = counts.get(c.team_id, 0) + 1
    return counts


@router.get("/database", response_class=HTMLResponse)
def database(request: Request, session: Session = Depends(get_session)):
    cars = ssvc.search_cars(session, "")
    return templates.TemplateResponse("database.html", {
        "request": request, "cars": cars, "team_names": _team_names(session),
    })


@router.get("/database/cars", response_class=HTMLResponse)
def database_cars(request: Request, q: str = "", category: str = "",
                  session: Session = Depends(get_session)):
    cat = Category(category) if category else None
    cars = ssvc.search_cars(session, q, category=cat)
    return templates.TemplateResponse("_car_rows.html", {
        "request": request, "cars": cars, "team_names": _team_names(session),
    })


@router.get("/database/teams", response_class=HTMLResponse)
def database_teams(request: Request, q: str = "",
                   session: Session = Depends(get_session)):
    teams = ssvc.search_teams(session, q)
    return templates.TemplateResponse("database.html", {
        "request": request, "cars": [], "teams": teams,
        "team_names": _team_names(session), "counts": _team_car_counts(session),
        "show_teams": True,
    })
