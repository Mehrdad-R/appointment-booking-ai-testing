from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import List
from uuid import uuid4

app = FastAPI(title="Appointment Booking API")

# Data models
class AppointmentCreate(BaseModel):
    title: str
    start: datetime
    end: datetime

class Appointment(AppointmentCreate):
    id: str

# In-memory "database"
APPOINTMENTS: List[Appointment] = []

# Helpers
def overlaps(start1: datetime, end1: datetime, start2: datetime, end2: datetime) -> bool:
    """Return True if two time ranges overlap."""
    return start1 < end2 and start2 < end1

# Routes
@app.get("/")
def root():
    return {"message": "Appointment Booking API is running"}

@app.get("/appointments", response_model=List[Appointment])
def list_appointments():
    return APPOINTMENTS

@app.post("/appointments", response_model=Appointment, status_code=201)
def create_appointment(payload: AppointmentCreate):
    # basic validation
    if payload.end <= payload.start:
        raise HTTPException(status_code=400, detail="end must be after start")

    # conflict detection against existing appointments
    for appt in APPOINTMENTS:
        if overlaps(payload.start, payload.end, appt.start, appt.end):
            raise HTTPException(
                status_code=409,
                detail=f"conflict: overlaps appointment {appt.id}"
            )

    new_appt = Appointment(id=str(uuid4()), **payload.model_dump())
    APPOINTMENTS.append(new_appt)
    return new_appt

@app.delete("/test/reset", status_code=204)
def reset_state():
    APPOINTMENTS.clear()