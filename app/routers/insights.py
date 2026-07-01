from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select
from app.db import get_session
from app.models import Season
from app.enums import Category
from app.services import insights
from app.routers.pages import templates

router = APIRouter()


@router.get("/insights", response_class=HTMLResponse)
def insights_hub(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "insights.html", {"request": request})


@router.get("/lanes", response_class=HTMLResponse)
def lanes_page(request: Request, season_id: Optional[int] = None, category: str = "",
               session: Session = Depends(get_session)):
    cat = Category(category) if category else None
    stats = insights.lane_stats(session, season_id=season_id, category=cat)
    seasons = session.exec(select(Season).order_by(Season.id.desc())).all()
    return templates.TemplateResponse(request, "lanes.html", {
        "request": request, "stats": stats, "seasons": seasons,
        "categories": list(Category), "sel_season": season_id, "sel_category": category})


@router.get("/health", response_class=HTMLResponse)
def health_page(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "health.html", {
        "request": request, "overview": insights.overview_counts(session),
        "checks": insights.health_checks(session)})
