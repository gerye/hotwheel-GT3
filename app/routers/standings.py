from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select
from app.db import get_session
from app.models import Car
from app.enums import Category
from app.services import seasons as ssvc, standings as st
from app.routers.pages import templates

router = APIRouter()


@router.get("/standings", response_class=HTMLResponse)
def standings_page(request: Request, category: str = "GT3",
                   season_mode: str = "season",
                   session: Session = Depends(get_session)):
    cat = Category(category)
    use_hist = season_mode == "history"
    cars = session.exec(select(Car).where(Car.category == cat)).all()
    cars.sort(key=lambda c: c.historical_mmr if use_hist else c.season_mmr,
              reverse=True)
    active = ssvc.get_active_season(session)
    board = st.team_board(session, active.id) if active else []
    return templates.TemplateResponse("standings.html", {
        "request": request, "cars": cars, "category": category,
        "season_mode": season_mode, "board": board,
        "use_hist": use_hist})
