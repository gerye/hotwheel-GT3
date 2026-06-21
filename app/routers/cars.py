from __future__ import annotations

from typing import Optional
from pathlib import Path
import uuid
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select
from app import config
from app.db import get_session
from app.models import Team
from app.enums import Category
from app.services import cars as csvc, teams as tsvc
from app.routers.pages import templates

router = APIRouter()


def _save_image(image: Optional[UploadFile]) -> Optional[str]:
    if image is None or not image.filename:
        return None
    ext = Path(image.filename).suffix.lower() or ".png"
    fname = f"{uuid.uuid4().hex}{ext}"
    dest = config.IMAGES_DIR / fname
    dest.write_bytes(image.file.read())
    return fname


def _teams(session: Session):
    return session.exec(select(Team).order_by(Team.name)).all()


@router.get("/cars/new", response_class=HTMLResponse)
def new_car(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse("car_form.html", {
        "request": request, "car": None, "teams": _teams(session),
        "action": "/cars", "error": None})


@router.post("/cars")
def create_car(request: Request, nickname: str = Form(...), category: str = Form(...),
               brand: str = Form(""), casting: str = Form(""),
               description: str = Form(""), team_id: str = Form(""),
               image: UploadFile = File(None),
               session: Session = Depends(get_session)):
    try:
        car = csvc.create_car(
            session, nickname=nickname, category=Category(category), brand=brand,
            casting=casting, description=description,
            team_id=int(team_id) if team_id else None,
            image_path=_save_image(image))
        return RedirectResponse(f"/cars/{car.id}", status_code=303)
    except (csvc.CarValidationError, tsvc.TeamValidationError) as e:
        return templates.TemplateResponse("car_form.html", {
            "request": request, "car": None, "teams": _teams(session),
            "action": "/cars", "error": str(e)}, status_code=200)


@router.get("/cars/{car_id}/edit", response_class=HTMLResponse)
def edit_car_form(car_id: int, request: Request,
                  session: Session = Depends(get_session)):
    from app.models import Car
    car = session.get(Car, car_id)
    return templates.TemplateResponse("car_form.html", {
        "request": request, "car": car, "teams": _teams(session),
        "action": f"/cars/{car_id}/edit", "error": None})


@router.post("/cars/{car_id}/edit")
def edit_car(car_id: int, request: Request, nickname: str = Form(...),
             category: str = Form(...), brand: str = Form(""), casting: str = Form(""),
             description: str = Form(""), team_id: str = Form(""),
             image: UploadFile = File(None),
             session: Session = Depends(get_session)):
    from app.models import Car
    fields = dict(nickname=nickname, category=Category(category), brand=brand,
                  casting=casting, description=description,
                  team_id=int(team_id) if team_id else None)
    img = _save_image(image)
    if img:
        fields["image_path"] = img
    try:
        csvc.update_car(session, car_id, **fields)
        return RedirectResponse(f"/cars/{car_id}", status_code=303)
    except (csvc.CarValidationError, tsvc.TeamValidationError) as e:
        car = session.get(Car, car_id)
        return templates.TemplateResponse("car_form.html", {
            "request": request, "car": car, "teams": _teams(session),
            "action": f"/cars/{car_id}/edit", "error": str(e)}, status_code=200)


@router.get("/cars/{car_id}", response_class=HTMLResponse)
def car_detail(car_id: int, request: Request,
               session: Session = Depends(get_session)):
    from app.models import Car
    car = session.get(Car, car_id)
    team_name = None
    if car.team_id:
        t = session.get(Team, car.team_id)
        team_name = t.name if t else None
    # 同类别按赛季 MMR 排名
    same = session.exec(select(Car).where(Car.category == car.category)
                        .order_by(Car.season_mmr.desc())).all()
    rank = next((i + 1 for i, c in enumerate(same) if c.id == car.id), None)
    honors: list[str] = []   # 计划二/三填充真实战绩
    return templates.TemplateResponse("car_detail.html", {
        "request": request, "car": car, "team_name": team_name,
        "rank": rank, "honors": honors})
