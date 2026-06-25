from __future__ import annotations

from urllib.parse import quote
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from app.db import get_session
from app.models import Team, Car
from app.enums import CarStatus
from app.services import market, salary as sal, budget as bud
from app.routers.pages import templates

router = APIRouter()


@router.get("/market", response_class=HTMLResponse)
def market_page(request: Request, session: Session = Depends(get_session)):
    ref = market.reference_season(session)
    teams_view, pool = [], []
    if ref is not None:
        for t in session.exec(select(Team)).all():
            roster = session.exec(select(Car).where(Car.team_id == t.id,
                     Car.status == CarStatus.ACTIVE)).all()
            teams_view.append({
                "team": t,
                "budget": bud.compute_budget(session, t, ref.id),
                "headroom": market.headroom(session, t.id, ref.id),
                "roster": [{"car": c, "salary": sal.compute_salary(session, c, ref.id)}
                           for c in roster]})
        for c in session.exec(select(Car).where(Car.team_id == None)).all():  # noqa: E711
            pool.append({"car": c, "salary": sal.compute_salary(session, c, ref.id)})
    return templates.TemplateResponse(request, "market.html", {
        "request": request, "ref": ref, "teams": teams_view, "pool": pool})


@router.post("/market/open")
def market_open(session: Session = Depends(get_session)):
    market.open_market(session)
    return RedirectResponse("/market", status_code=303)


@router.post("/market/recommend")
def market_recommend(session: Session = Depends(get_session)):
    ref = market.reference_season(session)
    if ref:
        market.recommend(session, ref.id)
    return RedirectResponse("/market", status_code=303)


@router.post("/market/sign")
def market_sign(car_id: int = Form(...), team_id: int = Form(...),
                session: Session = Depends(get_session)):
    ref = market.reference_season(session)
    try:
        market.sign(session, car_id, team_id, ref.id)
        return RedirectResponse("/market", status_code=303)
    except market.MarketError as e:
        return RedirectResponse(f"/market?err={quote(str(e))}", status_code=303)


@router.post("/market/release")
def market_release(car_id: int = Form(...), session: Session = Depends(get_session)):
    market.release(session, car_id)
    return RedirectResponse("/market", status_code=303)
