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

class AppointmentReschedule(BaseModel):
    start: datetime
    end: datetime

class Appointment(AppointmentCreate):
    id: str
    status: str

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

@app.get("/appointments/{appointment_id}", response_model=Appointment)
def get_appointment(appointment_id: str):
    for appt in APPOINTMENTS:
        if appt.id == appointment_id:
            return appt

    raise HTTPException(status_code=404, detail="appointment not found")

@app.post("/appointments", response_model=Appointment, status_code=201)
def create_appointment(payload: AppointmentCreate):
    # basic validation
    if payload.end <= payload.start:
        raise HTTPException(status_code=400, detail="end must be after start")

    # conflict detection against existing appointments
    for appt in APPOINTMENTS:
        if overlaps(payload.start, payload.end, appt.start, appt.end):
            raise HTTPException(status_code=409, detail=f"conflict: overlaps appointment {appt.id}")

    new_appt = Appointment(id=str(uuid4()), status="scheduled", **payload.model_dump())
    APPOINTMENTS.append(new_appt)
    return new_appt

@app.patch("/appointments/{appointment_id}/cancel", response_model=Appointment)
def cancel_appointment(appointment_id: str):
    for appt in APPOINTMENTS:
        if appt.id == appointment_id:
            if appt.status == "cancelled":
                raise HTTPException(status_code=400, detail="appointment is already cancelled")

            appt.status = "cancelled"
            return appt

    raise HTTPException(status_code=404, detail="appointment not found")

@app.patch("/appointments/{appointment_id}/reschedule", response_model=Appointment)
def reschedule_appointment(appointment_id: str, payload: AppointmentReschedule):
    if payload.end <= payload.start:
        raise HTTPException(status_code=400, detail="end must be after start")

    for appt in APPOINTMENTS:
        if appt.id == appointment_id:
            if appt.status == "cancelled":
                raise HTTPException(status_code=400, detail="cancelled appointments cannot be rescheduled")

            for other in APPOINTMENTS:
                if other.id != appointment_id and overlaps(payload.start, payload.end, other.start, other.end):
                    raise HTTPException(status_code=409, detail=f"conflict: overlaps appointment {other.id}")

            appt.start = payload.start
            appt.end = payload.end
            return appt

    raise HTTPException(status_code=404, detail="appointment not found")

@app.delete("/test/reset", status_code=204)
def reset_state():
    APPOINTMENTS.clear()