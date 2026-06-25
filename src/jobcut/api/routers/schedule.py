"""Schedule the daily run from the console (installs launchd/cron under the hood)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import scheduler

router = APIRouter(prefix="/schedule", tags=["schedule"])


class ScheduleIn(BaseModel):
    enabled: bool = False
    frequency: str = "daily"          # daily | weekdays | every_n
    interval_days: int = 2            # used when frequency == every_n
    hour: int = 7
    minute: int = 30


@router.get("")
def get_schedule():
    return scheduler.get()


@router.put("")
def put_schedule(body: ScheduleIn):
    try:
        return scheduler.set_schedule(body.model_dump())
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("")
def delete_schedule():
    return scheduler.clear()
