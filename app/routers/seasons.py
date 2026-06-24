from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from app.db import get_session
from app.models import Season, Race
from app.services import seasons as svc, standings as st, admin as admin_svc
from app.routers.pages import templates

router = APIRouter()


@router.post("/admin/wipe-all")
def wipe_all(session: Session = Depends(get_session)):
    admin_svc.wipe_all_data(session)
    return RedirectResponse("/database", status_code=303)


@router.get("/seasons", response_class=HTMLResponse)
def seasons_page(request: Request, session: Session = Depends(get_session)):
    seasons = session.exec(select(Season).order_by(Season.id.desc())).all()
    return templates.TemplateResponse("seasons.html", {
        "request": request, "seasons": seasons,
        "active": svc.get_active_season(session)})


@router.post("/seasons")
def start_season(request: Request, name: str = Form(...),
                 session: Session = Depends(get_session)):
    try:
        svc.start_season(session, name=name)
    except svc.SeasonError:
        pass
    return RedirectResponse("/seasons", status_code=303)


@router.post("/seasons/{season_id}/end")
def end_season(season_id: int, session: Session = Depends(get_session)):
    try:
        svc.end_season(session, season_id)
    except svc.SeasonError:
        pass
    return RedirectResponse("/seasons", status_code=303)


@router.get("/seasons/{season_id}", response_class=HTMLResponse)
def season_detail(season_id: int, request: Request,
                  session: Session = Depends(get_session)):
    season = session.get(Season, season_id)
    board = st.team_board(session, season_id)
    races = session.exec(select(Race).where(Race.season_id == season_id)).all()
    return templates.TemplateResponse("season_detail.html", {
        "request": request, "season": season, "board": board, "races": races})
