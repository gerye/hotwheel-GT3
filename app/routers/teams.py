from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from app.db import get_session
from app.models import Team
from app.enums import TeamType
from app.services import teams as tsvc, standings as st, seasons as ssvc
from app.routers.pages import templates

router = APIRouter()


@router.get("/teams/new", response_class=HTMLResponse)
def new_team(request: Request):
    return templates.TemplateResponse("team_form.html", {
        "request": request, "team": None, "action": "/teams", "error": None})


@router.post("/teams")
def create_team(request: Request, type: str = Form(...), brand: str = Form(""),
                name: str = Form(""), session: Session = Depends(get_session)):
    try:
        team = tsvc.create_team(session, type=TeamType(type),
                                brand=brand or None, name=name or None)
        return RedirectResponse(f"/teams/{team.id}", status_code=303)
    except tsvc.TeamValidationError as e:
        return templates.TemplateResponse("team_form.html", {
            "request": request, "team": None, "action": "/teams",
            "error": str(e)}, status_code=200)


@router.get("/teams/{team_id}", response_class=HTMLResponse)
def team_detail(team_id: int, request: Request,
                session: Session = Depends(get_session)):
    from app.models import Car
    from app.config import MAX_CARS_PER_CATEGORY
    team = session.get(Team, team_id)
    members = session.exec(select(Car).where(Car.team_id == team_id)
                           .order_by(Car.category)).all()
    capacity: dict[str, int] = {}
    for c in members:
        capacity[c.category.value] = capacity.get(c.category.value, 0) + 1
    active = ssvc.get_active_season(session)
    season_points = st.team_season_points(session, team_id, active.id) if active else 0
    sources = (st.team_point_sources(session, team_id, active.id) if active else [])
    point_sources = [f"+{e.points} {e.description}" for e in sources]
    return templates.TemplateResponse("team_detail.html", {
        "request": request, "team": team, "members": members,
        "capacity": capacity, "season_points": season_points,
        "point_sources": point_sources})
