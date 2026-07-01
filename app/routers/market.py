from __future__ import annotations

from urllib.parse import quote
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session
from app.db import get_session
from app.models import Team
from app.enums import Category
from app.services import market, market_draft as md, budget as bud
from app.routers.pages import templates

router = APIRouter()


def _redirect(msg: str = ""):
    url = "/market" + (f"?err={quote(msg)}" if msg else "")
    return RedirectResponse(url, status_code=303)


@router.get("/market", response_class=HTMLResponse)
def market_page(request: Request, err: str = "", session: Session = Depends(get_session)):
    ref = market.reference_season(session)
    draft = md.get_draft(session)
    queue = md.draft_queue(session) if draft else []
    current = None
    if draft and draft.current_team_id:
        tid = draft.current_team_id
        team = session.get(Team, tid)
        cats = []
        locked = md.locked_categories(draft)
        for cat in Category:
            longs = md._long_cars(session, tid, cat)
            cats.append({
                "category": cat,
                "locked": cat in locked,
                "pool": md.category_pool(session, tid, cat),
                "rec": md.category_recommendation(session, tid, cat),
                "has_long": bool(longs),
                "longs": longs,
                "free_slots": md.MAX_CARS_PER_CATEGORY - len(longs),
            })
        current = {"team": team, "cats": cats,
                   "headroom": market.headroom(session, tid, draft.reference_season_id),
                   "budget": bud.compute_budget(session, team, draft.reference_season_id)}
    return templates.TemplateResponse(request, "market.html", {
        "request": request, "ref": ref, "draft": draft,
        "queue": queue, "current": current, "err": err})


@router.post("/market/open")
def market_open(session: Session = Depends(get_session)):
    try:
        md.open_draft(session)
        return _redirect()
    except md.DraftError as e:
        return _redirect(str(e))


@router.post("/market/enter")
def market_enter(team_id: int = Form(...), session: Session = Depends(get_session)):
    try:
        md.enter_team(session, team_id); return _redirect()
    except md.DraftError as e:
        return _redirect(str(e))


@router.post("/market/lock")
def market_lock(team_id: int = Form(...), category: str = Form(...),
                slot1: str = Form(""), slot2: str = Form(""),
                session: Session = Depends(get_session)):
    slots = [int(slot1) if slot1 else None, int(slot2) if slot2 else None]
    try:
        md.lock_category(session, team_id, Category(category), slots); return _redirect()
    except md.DraftError as e:
        return _redirect(str(e))


@router.post("/market/unlock")
def market_unlock(team_id: int = Form(...), category: str = Form(...),
                  session: Session = Depends(get_session)):
    try:
        md.unlock_category(session, team_id, Category(category)); return _redirect()
    except md.DraftError as e:
        return _redirect(str(e))


@router.post("/market/confirm")
def market_confirm(team_id: int = Form(...), session: Session = Depends(get_session)):
    try:
        md.confirm_team(session, team_id); return _redirect()
    except md.DraftError as e:
        return _redirect(str(e))


@router.post("/market/reset")
def market_reset(session: Session = Depends(get_session)):
    md.reset_draft(session); return _redirect()


@router.post("/market/finalize")
def market_finalize(session: Session = Depends(get_session)):
    md.close_draft(session)
    return RedirectResponse("/seasons", status_code=303)
