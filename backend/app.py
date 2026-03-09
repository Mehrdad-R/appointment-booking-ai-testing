from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import List
from uuid import uuid4
import sqlite3

app = FastAPI(title="Appointment Booking API")
DB_FILE = "appointments.db"

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
    

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""CREATE TABLE IF NOT EXISTS appointments (id TEXT PRIMARY KEY, title TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL, status TEXT NOT NULL)""")

    conn.commit()
    conn.close()

# Helpers
def overlaps(start1: datetime, end1: datetime, start2: datetime, end2: datetime) -> bool:
    """Return True if two time ranges overlap."""
    return start1 < end2 and start2 < end1

@app.on_event("startup")
def startup_event():
    init_db()

# Routes
@app.get("/")
def root():
    return {"message": "Appointment Booking API is running"}

@app.get("/appointments", response_model=List[Appointment])
def list_appointments():
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("SELECT * FROM appointments").fetchall()

    conn.close()

    return [Appointment(**dict(row)) for row in rows]

@app.get("/appointments/{appointment_id}", response_model=Appointment)
def get_appointment(appointment_id: str):
    # Open a database connection
    conn = get_connection()
    cursor = conn.cursor()

    # Query the appointment by ID
    row = cursor.execute(
        "SELECT * FROM appointments WHERE id = ?",
        (appointment_id,)
    ).fetchone()

    conn.close()

    # If no appointment was found return 404
    if row is None:
        raise HTTPException(status_code=404, detail="appointment not found")

    # Convert the database row into an Appointment object
    return Appointment(**dict(row))

@app.post("/appointments", response_model=Appointment, status_code=201)
def create_appointment(payload: AppointmentCreate):
    # Validate that the end time occurs after the start time
    if payload.end <= payload.start:
        raise HTTPException(status_code=400, detail="end must be after start")

    # Open a connection to the SQLite database
    conn = get_connection()
    cursor = conn.cursor()

    # Retrieve all existing appointments to check for time conflicts
    rows = cursor.execute("SELECT * FROM appointments").fetchall()

    for row in rows:
        appt_start = datetime.fromisoformat(row["start"])
        appt_end = datetime.fromisoformat(row["end"])

        if overlaps(payload.start, payload.end, appt_start, appt_end):
            conn.close()
            raise HTTPException(status_code=409, detail=f"conflict: overlaps appointment {row['id']}")

    # Create a new appointment object with a generated UUID with an initial status of "scheduled"
    new_appt = Appointment(id=str(uuid4()), status="scheduled", **payload.model_dump())

    # Insert the new appointment into the SQLite database
    cursor.execute(""" INSERT INTO appointments (id, title, start, end, status) VALUES (?, ?, ?, ?, ?) """,
        (new_appt.id, new_appt.title, new_appt.start.isoformat(), new_appt.end.isoformat(), new_appt.status)
    )

    # Save the changes to the database
    conn.commit()
    # Close the database connection
    conn.close()
    # Return the newly created appointment
    return new_appt

@app.patch("/appointments/{appointment_id}/cancel", response_model=Appointment)
def cancel_appointment(appointment_id: str):
    # Open a database connection
    conn = get_connection()
    cursor = conn.cursor()

    # Look up the appointment by ID
    row = cursor.execute(
        "SELECT * FROM appointments WHERE id = ?",
        (appointment_id,)
    ).fetchone()

    # If the appointment does not exist return 404
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="appointment not found")

    # If the appointment is already cancelled reject the request
    if row["status"] == "cancelled":
        conn.close()
        raise HTTPException(status_code=400, detail="appointment is already cancelled")

    # Update the appointment status in the database
    cursor.execute(
        "UPDATE appointments SET status = ? WHERE id = ?",
        ("cancelled", appointment_id)
    )
    conn.commit()

    # Retrieve the updated appointment
    updated_row = cursor.execute(
        "SELECT * FROM appointments WHERE id = ?",
        (appointment_id,)
    ).fetchone()

    conn.close()

    return Appointment(**dict(updated_row))

@app.patch("/appointments/{appointment_id}/reschedule", response_model=Appointment)
def reschedule_appointment(appointment_id: str, payload: AppointmentReschedule):
    # Validate that the end time occurs after the start time
    if payload.end <= payload.start:
        raise HTTPException(status_code=400, detail="end must be after start")

    # Open a database connection
    conn = get_connection()
    cursor = conn.cursor()

    # Look up the appointment being rescheduled
    row = cursor.execute(
        "SELECT * FROM appointments WHERE id = ?",
        (appointment_id,)
    ).fetchone()

    # If the appointment does not exist return 404
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="appointment not found")

    # If the appointment is cancelled reject the request
    if row["status"] == "cancelled":
        conn.close()
        raise HTTPException(status_code=400, detail="cancelled appointments cannot be rescheduled")

    # Retrieve all other appointments to check for overlap conflicts
    other_rows = cursor.execute(
        "SELECT * FROM appointments WHERE id != ?",
        (appointment_id,)
    ).fetchall()

    for other in other_rows:
        other_start = datetime.fromisoformat(other["start"])
        other_end = datetime.fromisoformat(other["end"])

        if overlaps(payload.start, payload.end, other_start, other_end):
            conn.close()
            raise HTTPException(status_code=409, detail=f"conflict: overlaps appointment {other['id']}")

    # Update the appointment in the database
    cursor.execute(
        "UPDATE appointments SET start = ?, end = ? WHERE id = ?",
        (
            payload.start.isoformat(),
            payload.end.isoformat(),
            appointment_id
        )
    )
    conn.commit()

    # Retrieve the updated appointment
    updated_row = cursor.execute(
        "SELECT * FROM appointments WHERE id = ?",
        (appointment_id,)
    ).fetchone()

    conn.close()

    return Appointment(**dict(updated_row))

@app.delete("/test/reset", status_code=204)
def reset_state():
    # Open a database connection
    conn = get_connection()
    cursor = conn.cursor()

    # Delete all rows from the appointments table
    cursor.execute("DELETE FROM appointments")
    conn.commit()
    conn.close()