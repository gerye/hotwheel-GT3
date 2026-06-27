from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from app.db import get_session
from app.models import Team
from app.enums import TeamType
from app.services import teams as tsvc, standings as st, seasons as ssvc, budget as bud
from app.services import market
from app.routers.pages import templates

router = APIRouter()


@router.get("/teams/new", response_class=HTMLResponse)
def new_team(request: Request):
    return templates.TemplateResponse(request, "team_form.html", {
        "request": request, "team": None, "action": "/teams", "error": None})


@router.post("/teams")
def create_team(request: Request, type: str = Form(...), brand: str = Form(""),
                name: str = Form(""), alias_f1: str = Form(""),
                alias_gt3: str = Form(""), alias_road: str = Form(""),
                session: Session = Depends(get_session)):
    try:
        team = tsvc.create_team(session, type=TeamType(type),
                                brand=brand or None, name=name or None,
                                alias_f1=alias_f1, alias_gt3=alias_gt3,
                                alias_road=alias_road)
        return RedirectResponse(f"/teams/{team.id}", status_code=303)
    except tsvc.TeamValidationError as e:
        return templates.TemplateResponse(request, "team_form.html", {
            "request": request, "team": None, "action": "/teams",
            "error": str(e)}, status_code=200)


@router.get("/teams/{team_id}/edit", response_class=HTMLResponse)
def edit_team_form(team_id: int, request: Request,
                   session: Session = Depends(get_session)):
    team = session.get(Team, team_id)
    return templates.TemplateResponse(request, "team_form.html", {
        "request": request, "team": team,
        "action": f"/teams/{team_id}/edit", "error": None})


@router.post("/teams/{team_id}/edit")
def edit_team(team_id: int, request: Request, type: str = Form(...),
              brand: str = Form(""), name: str = Form(""),
              alias_f1: str = Form(""), alias_gt3: str = Form(""),
              alias_road: str = Form(""),
              session: Session = Depends(get_session)):
    try:
        tsvc.update_team(session, team_id, type=TeamType(type),
                         brand=brand or None, name=name or None,
                         alias_f1=alias_f1, alias_gt3=alias_gt3,
                         alias_road=alias_road)
        return RedirectResponse(f"/teams/{team_id}", status_code=303)
    except tsvc.TeamValidationError as e:
        team = session.get(Team, team_id)
        return templates.TemplateResponse(request, "team_form.html", {
            "request": request, "team": team,
            "action": f"/teams/{team_id}/edit", "error": str(e)},
            status_code=200)


@router.post("/teams/{team_id}/delete")
def delete_team(team_id: int, session: Session = Depends(get_session)):
    tsvc.delete_team(session, team_id)
    return RedirectResponse("/database/teams", status_code=303)


@router.get("/teams/{team_id}", response_class=HTMLResponse)
def team_detail(team_id: int, request: Request,
                session: Session = Depends(get_session)):
    from app.models import Car
    from app.enums import CarStatus, Category
    team = session.get(Team, team_id)
    members = session.exec(select(Car).where(Car.team_id == team_id)
                           .order_by(Car.category)).all()
    capacity: dict[str, int] = {}      # 现役占用(退役不计)
    for c in members:
        if c.status.is_active:
            capacity[c.category.value] = capacity.get(c.category.value, 0) + 1
    active = ssvc.get_active_season(session)
    season_points = st.team_season_points(session, team_id, active.id) if active else 0
    sources = (st.team_point_sources(session, team_id, active.id) if active else [])
    point_sources = [f"+{e.points} {e.description}" for e in sources]
    specifics = [(c.value, team.specific_name(c)) for c in Category]
    # 本赛季(由上一已结束季决定)与 下赛季预计(由进行中季实时推算)
    this_id, next_id = market.season_pair(session)
    budget_now = bud.compute_budget(session, team, this_id)
    committed_now = market.committed_salary(session, team.id, this_id)
    budget_next = bud.compute_budget(session, team, next_id)
    committed_next = market.committed_salary(session, team.id, next_id)
    return templates.TemplateResponse(request, "team_detail.html", {
        "request": request, "team": team, "members": members,
        "capacity": capacity, "season_points": season_points,
        "point_sources": point_sources, "specifics": specifics,
        "budget_now": budget_now, "committed_now": committed_now,
        "budget_next": budget_next, "committed_next": committed_next})
