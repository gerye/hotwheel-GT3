from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from app.db import get_session
from app.models import Car, Race, RaceRound, Group, GroupMember, Heat, HeatResult
from app.enums import Category, ProLevel, RaceFormat
from app.enums import RaceStatus
from app.services import tournament as T, seasons as ssvc, scoring
from app.routers.pages import templates

router = APIRouter()


def eligible_cars(session: Session, category: Category, *, pro: bool) -> list[Car]:
    stmt = select(Car).where(Car.category == category)
    cars = session.exec(stmt.order_by(Car.nickname)).all()
    if pro:                                 # 专业赛排除无车队的车
        cars = [c for c in cars if c.team_id is not None]
    return cars


@router.get("/races", response_class=HTMLResponse)
def races_page(request: Request, session: Session = Depends(get_session)):
    races = session.exec(select(Race).order_by(Race.id.desc())).all()
    return templates.TemplateResponse("races.html", {
        "request": request, "races": races,
        "active": ssvc.get_active_season(session)})


@router.get("/races/new", response_class=HTMLResponse)
def new_race(request: Request, category: str = "GT3", pro_level: str = "专业",
             format: str = "单人锦标赛", session: Session = Depends(get_session)):
    cat = Category(category)
    cars = eligible_cars(session, cat, pro=(pro_level == "专业"))
    return templates.TemplateResponse("race_new.html", {
        "request": request, "cars": cars, "category": category,
        "pro_level": pro_level, "format": format})


@router.post("/races")
def create_race(request: Request, category: str = Form(...),
                pro_level: str = Form(...), format: str = Form(...),
                car_ids: list[int] = Form(default=[]),
                session: Session = Depends(get_session)):
    try:
        race = T.create_race(session, category=Category(category),
                             pro_level=ProLevel(pro_level),
                             format=RaceFormat(format), car_ids=car_ids)
        return RedirectResponse(f"/races/{race.id}", status_code=303)
    except Exception as e:
        cat = Category(category)
        cars = eligible_cars(session, cat, pro=(pro_level == "专业"))
        return templates.TemplateResponse("race_new.html", {
            "request": request, "cars": cars, "category": category,
            "pro_level": pro_level, "format": format, "error": str(e)},
            status_code=200)


@router.get("/races/{race_id}", response_class=HTMLResponse)
def race_detail(race_id: int, request: Request,
                session: Session = Depends(get_session)):
    race = session.get(Race, race_id)
    rnd = session.exec(select(RaceRound).where(RaceRound.race_id == race_id)
                       .order_by(RaceRound.number.desc())).first()
    groups = session.exec(select(Group).where(Group.round_id == rnd.id)).all()
    view = []
    names = {c.id: c.nickname for c in session.exec(select(Car)).all()}
    for g in groups:
        members = [names[m.car_id] for m in session.exec(select(GroupMember)
                   .where(GroupMember.group_id == g.id)).all()]
        heats = session.exec(select(Heat).where(Heat.group_id == g.id)
                             .order_by(Heat.number)).all()
        heat_views = []
        for h in heats:
            rows = session.exec(select(HeatResult).where(
                HeatResult.heat_id == h.id).order_by(HeatResult.lane)).all()
            heat_views.append({"heat": h, "rows": rows, "names": names})
        view.append({"group": g, "members": members, "heats": heat_views})
    final_ranking = None
    if race.status == RaceStatus.FINISHED and groups:
        totals = scoring.group_totals(T._group_results(session, groups[0].id))
        final_ranking = scoring.final_ranking(totals)
    return templates.TemplateResponse("race_detail.html", {
        "request": request, "race": race, "round": rnd, "groups": view,
        "names": names, "final_ranking": final_ranking})


@router.post("/races/{race_id}/heats/{heat_id}")
async def record_heat(race_id: int, heat_id: int, request: Request,
                      session: Session = Depends(get_session)):
    form = await request.form()
    ranks, dnf = {}, set()
    for k, v in form.items():
        if k.startswith("rank_") and v:
            ranks[int(k[5:])] = int(v)
        if k.startswith("dnf_"):
            dnf.add(int(k[4:]))
    T.record_heat(session, heat_id, ranks=ranks, dnf=dnf)
    return RedirectResponse(f"/races/{race_id}", status_code=303)


@router.post("/races/{race_id}/heats/{heat_id}/undo")
def undo_heat(race_id: int, heat_id: int,
              session: Session = Depends(get_session)):
    T.undo_heat(session, heat_id)
    return RedirectResponse(f"/races/{race_id}", status_code=303)


@router.post("/races/{race_id}/advance")
def advance(race_id: int, request: Request,
            session: Session = Depends(get_session)):
    result = T.advance_round(session, race_id)
    if result.kind == "finished":
        # 把最终名次暂存到查询参数,详情页读取
        ids = ",".join(str(i) for i in result.ranking)
        return RedirectResponse(f"/races/{race_id}?ranking={ids}", status_code=303)
    if result.kind == "needs_decision":
        gid = result.pending_group_ids[0]
        return RedirectResponse(f"/races/{race_id}/tie/{gid}", status_code=303)
    return RedirectResponse(f"/races/{race_id}", status_code=303)


@router.get("/races/{race_id}/tie/{group_id}", response_class=HTMLResponse)
def tie_page(race_id: int, group_id: int, request: Request,
             session: Session = Depends(get_session)):
    adv = T.settle_group(session, group_id)
    names = {c.id: c.nickname for c in session.exec(select(Car)).all()}
    return templates.TemplateResponse("race_tie.html", {
        "request": request, "race_id": race_id, "group_id": group_id,
        "tied": adv.tie_between, "names": names})


@router.post("/races/{race_id}/tie/{group_id}")
def resolve_tie(race_id: int, group_id: int, winner_car_id: int = Form(...),
                session: Session = Depends(get_session)):
    T.resolve_tie(session, group_id, winner_car_id=winner_car_id)
    return RedirectResponse(f"/races/{race_id}/advance" if False else
                            f"/races/{race_id}", status_code=303)
