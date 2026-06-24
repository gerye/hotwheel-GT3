from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from app.db import get_session
from app.models import (Car, Team, Race, RaceRound, Group, GroupMember,
                        Heat, HeatResult)
from app.enums import Category, ProLevel, RaceFormat, CarStatus
from app.enums import RaceStatus
from app.services import tournament as T, seasons as ssvc, scoring
from app.routers.pages import templates

router = APIRouter()


def eligible_cars(session: Session, category: Category, *, pro: bool) -> list[Car]:
    stmt = select(Car).where(Car.category == category)
    cars = session.exec(stmt.order_by(Car.nickname)).all()
    if pro:                                 # 专业赛仅限现役
        cars = [c for c in cars if c.status == CarStatus.ACTIVE]
    return cars                             # 表演赛:任何状态都可


def eligible_teams(session: Session, category: Category) -> list[Team]:
    """车队锦标赛可选车队:在该类别下至少有 1 个现役车手的车队。"""
    team_ids = {c.team_id for c in session.exec(
        select(Car).where(Car.category == category,
                          Car.status == CarStatus.ACTIVE,
                          Car.team_id.is_not(None))).all()}
    if not team_ids:
        return []
    return session.exec(select(Team).where(Team.id.in_(team_ids))
                        .order_by(Team.name)).all()


@router.get("/races", response_class=HTMLResponse)
def races_page(request: Request, session: Session = Depends(get_session)):
    races = session.exec(select(Race).order_by(Race.id.desc())).all()
    return templates.TemplateResponse("races.html", {
        "request": request, "races": races,
        "active": ssvc.get_active_season(session)})


def _new_race_context(request: Request, session: Session, *, category: str,
                      pro_level: str, format: str, error: Optional[str] = None):
    cat = Category(category)
    is_team = format == RaceFormat.TEAM.value
    ctx = {"request": request, "category": category, "pro_level": pro_level,
           "format": format, "is_team": is_team}
    if is_team:
        ctx["teams"] = eligible_teams(session, cat)
    else:
        ctx["cars"] = eligible_cars(session, cat, pro=(pro_level == "专业"))
    if error is not None:
        ctx["error"] = error
    return templates.TemplateResponse("race_new.html", ctx)


@router.get("/races/new", response_class=HTMLResponse)
def new_race(request: Request, category: str = "GT3", pro_level: str = "专业",
             format: str = "单人锦标赛", session: Session = Depends(get_session)):
    return _new_race_context(request, session, category=category,
                             pro_level=pro_level, format=format)


@router.post("/races")
def create_race(request: Request, category: str = Form(...),
                pro_level: str = Form(...), format: str = Form(...),
                car_ids: list[int] = Form(default=[]),
                team_ids: list[int] = Form(default=[]),
                session: Session = Depends(get_session)):
    try:
        if RaceFormat(format) == RaceFormat.TEAM:
            race = T.create_team_race(session, category=Category(category),
                                      pro_level=ProLevel(pro_level),
                                      team_ids=team_ids)
        else:
            race = T.create_race(session, category=Category(category),
                                 pro_level=ProLevel(pro_level),
                                 format=RaceFormat(format), car_ids=car_ids)
        return RedirectResponse(f"/races/{race.id}", status_code=303)
    except Exception as e:
        return _new_race_context(request, session, category=category,
                                 pro_level=pro_level, format=format,
                                 error=str(e))


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
        gms = session.exec(select(GroupMember)
                           .where(GroupMember.group_id == g.id)).all()
        members = [names[m.car_id] for m in gms]
        member_cars = [session.get(Car, m.car_id) for m in gms]
        heats = session.exec(select(Heat).where(Heat.group_id == g.id)
                             .order_by(Heat.number)).all()
        heat_views = []
        for h in heats:
            rows = session.exec(select(HeatResult).where(
                HeatResult.heat_id == h.id).order_by(HeatResult.lane)).all()
            heat_views.append({"heat": h, "rows": rows, "names": names})
        gv = {"group": g, "members": members, "member_cars": member_cars,
              "heats": heat_views}
        gv["board"] = T.group_scoreboard(session, g, race)   # 实时积分榜
        if race.format == RaceFormat.TEAM:   # 车队赛:用具体名展示两队
            ta = session.get(Team, g.team_a_id) if g.team_a_id else None
            tb = session.get(Team, g.team_b_id) if g.team_b_id else None
            gv["team_a"] = ta.specific_name(race.category) if ta else None
            gv["team_b"] = tb.specific_name(race.category) if tb else None
        view.append(gv)
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
    try:
        T.record_heat(session, heat_id, ranks=ranks, dnf=dnf)
    except T.HeatInputError as e:
        from urllib.parse import quote
        return RedirectResponse(f"/races/{race_id}?err={quote(str(e))}#heat{heat_id}",
                                status_code=303)
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
    return RedirectResponse(f"/races/{race_id}", status_code=303)
