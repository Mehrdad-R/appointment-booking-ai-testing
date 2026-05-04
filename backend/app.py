from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from typing import List
from uuid import uuid4
from typing import List, Optional
import hashlib
from pathlib import Path
import json
import os
try:
    from backend.db import get_connection, initialize_schema
except ImportError:
    from db import get_connection, initialize_schema


app = FastAPI(title="Appointment Booking API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
BASE_DIR = Path(__file__).resolve().parent
AGENT_DIR = BASE_DIR / "agent"
AGENT_PLAN_FILE = AGENT_DIR / "test_plan.json"
AGENT_SUMMARY_FILE = AGENT_DIR / "agent_decision_summary.md"
AGENT_HISTORY_FILE = AGENT_DIR / "history_runtime.json"

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
    customer_id: Optional[str] = None

class LoginRequest(BaseModel):
    username: str
    password: str

class UserInfo(BaseModel):
    id: str
    username: str
    role: str

class LoginResponse(BaseModel):
    token: str
    user: UserInfo

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def seed_demo_users():
    conn = get_connection()
    cursor = conn.cursor()

    demo_users = [
        {
            "id": str(uuid4()),
            "username": "customer1",
            "password_hash": hash_password("customer123"),
            "role": "customer"
        },
        {
            "id": str(uuid4()),
            "username": "customer2",
            "password_hash": hash_password("customer234"),
            "role": "customer"
        },
        {
            "id": str(uuid4()),
            "username": "employee1",
            "password_hash": hash_password("employee123"),
            "role": "employee"
        },
        {
            "id": str(uuid4()),
            "username": "admin1",
            "password_hash": hash_password("admin123"),
            "role": "admin"
        }
    ]

    for user in demo_users:
        existing = cursor.execute(
            "SELECT * FROM users WHERE username = ?",
            (user["username"],)
        ).fetchone()

        if existing is None:
            cursor.execute(
                """
                INSERT INTO users (id, username, password_hash, role)
                VALUES (?, ?, ?, ?)
                """,
                (user["id"], user["username"], user["password_hash"], user["role"])
            )

    conn.commit()
    conn.close()

def get_current_user(authorization: Optional[str]):
    if not authorization:
        raise HTTPException(status_code=401, detail="missing authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="invalid authorization format")

    token = authorization.replace("Bearer ", "", 1).strip()

    conn = get_connection()
    cursor = conn.cursor()

    row = cursor.execute(
        """
        SELECT users.id, users.username, users.role
        FROM sessions
        JOIN users ON sessions.user_id = users.id
        WHERE sessions.token = ?
        """,
        (token,)
    ).fetchone()

    conn.close()

    if row is None:
        raise HTTPException(status_code=401, detail="invalid or expired session")

    return dict(row)

def require_role(user, allowed_roles):
    if user["role"] not in allowed_roles:
        raise HTTPException(status_code=403, detail="forbidden")
    
def load_json_if_exists(path: Path):
    if not path.exists():
        return None

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_text_if_exists(path: Path):
    if not path.exists():
        return None

    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def save_agent_snapshot_to_db(plan: dict, summary: Optional[str], history: Optional[dict]):
    conn = get_connection()
    cursor = conn.cursor()

    build_run_id = str(uuid4())
    created_at = datetime.utcnow().isoformat()

    selected_groups_json = json.dumps(plan.get("selected_groups", []))

    cursor.execute(
        """
        INSERT INTO agent_build_runs (
            id, created_at, decision_source, risk_level,
            selected_groups_json, reason, summary_text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            build_run_id,
            created_at,
            plan.get("decision_source"),
            plan.get("risk_level"),
            selected_groups_json,
            plan.get("reason"),
            summary
        )
    )

    for file_path in plan.get("changed_files", []):
        cursor.execute(
            """
            INSERT INTO agent_build_changed_files (build_run_id, file_path)
            VALUES (?, ?)
            """,
            (build_run_id, file_path)
        )

    for test_name in plan.get("priority_tests", []):
        cursor.execute(
            """
            INSERT INTO agent_build_priority_tests (build_run_id, test_name)
            VALUES (?, ?)
            """,
            (build_run_id, test_name)
        )

    if history:
        for item in history.get("recent_failures", []):
            cursor.execute(
                """
                INSERT INTO agent_recent_failures (
                    build_run_id, test_name, failure_reason, module_name, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    build_run_id,
                    item.get("test_name"),
                    item.get("failure_reason"),
                    item.get("module"),
                    created_at
                )
            )

        for item in history.get("slow_tests", []):
            cursor.execute(
                """
                INSERT INTO agent_slow_tests (
                    build_run_id, test_name, estimated_runtime, created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    build_run_id,
                    item.get("test_name"),
                    item.get("estimated_runtime"),
                    created_at
                )
            )

        for module_name in history.get("high_risk_modules", []):
            cursor.execute(
                """
                INSERT INTO agent_high_risk_modules (
                    build_run_id, module_name, created_at
                )
                VALUES (?, ?, ?)
                """,
                (
                    build_run_id,
                    module_name,
                    created_at
                )
            )

    conn.commit()
    conn.close()

    return build_run_id


def get_latest_agent_snapshot_from_db():
    conn = get_connection()
    cursor = conn.cursor()

    build_row = cursor.execute(
        """
        SELECT *
        FROM agent_build_runs
        ORDER BY created_at DESC
        LIMIT 1
        """
    ).fetchone()

    if build_row is None:
        conn.close()
        return None

    build_run_id = build_row["id"]

    changed_files_rows = cursor.execute(
        """
        SELECT file_path
        FROM agent_build_changed_files
        WHERE build_run_id = ?
        """,
        (build_run_id,)
    ).fetchall()

    priority_test_rows = cursor.execute(
        """
        SELECT test_name
        FROM agent_build_priority_tests
        WHERE build_run_id = ?
        """,
        (build_run_id,)
    ).fetchall()

    recent_failure_rows = cursor.execute(
        """
        SELECT test_name, failure_reason, module_name
        FROM agent_recent_failures
        WHERE build_run_id = ?
        ORDER BY id DESC
        """,
        (build_run_id,)
    ).fetchall()

    slow_test_rows = cursor.execute(
        """
        SELECT test_name, estimated_runtime
        FROM agent_slow_tests
        WHERE build_run_id = ?
        ORDER BY id DESC
        """,
        (build_run_id,)
    ).fetchall()

    high_risk_rows = cursor.execute(
        """
        SELECT module_name
        FROM agent_high_risk_modules
        WHERE build_run_id = ?
        ORDER BY id DESC
        """,
        (build_run_id,)
    ).fetchall()

    conn.close()

    plan = {
        "decision_source": build_row["decision_source"],
        "risk_level": build_row["risk_level"],
        "selected_groups": json.loads(build_row["selected_groups_json"] or "[]"),
        "priority_tests": [row["test_name"] for row in priority_test_rows],
        "changed_files": [row["file_path"] for row in changed_files_rows],
        "reason": build_row["reason"]
    }

    history = {
        "recent_failures": [
            {
                "test_name": row["test_name"],
                "failure_reason": row["failure_reason"],
                "module": row["module_name"]
            }
            for row in recent_failure_rows
        ],
        "slow_tests": [
            {
                "test_name": row["test_name"],
                "estimated_runtime": row["estimated_runtime"]
            }
            for row in slow_test_rows
        ],
        "high_risk_modules": [row["module_name"] for row in high_risk_rows]
    }

    return {
        "plan": plan,
        "history": history,
        "summary": build_row["summary_text"]
    }

def init_db():
    initialize_schema()
    seed_demo_users()

# Helpers
def overlaps(start1: datetime, end1: datetime, start2: datetime, end2: datetime) -> bool:
    """Return True if two time ranges overlap."""
    start1 = start1.replace(tzinfo=None)
    end1 = end1.replace(tzinfo=None)
    start2 = start2.replace(tzinfo=None)
    end2 = end2.replace(tzinfo=None)

    return start1 < end2 and start2 < end1

@app.on_event("startup")
def startup_event():
    init_db()

# Routes
@app.get("/")
def root():
    return {"message": "Appointment Booking API is running"}

@app.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    conn = get_connection()
    cursor = conn.cursor()

    user_row = cursor.execute(
        "SELECT * FROM users WHERE username = ?",
        (payload.username,)
    ).fetchone()

    if user_row is None:
        conn.close()
        raise HTTPException(status_code=401, detail="invalid username or password")

    incoming_hash = hash_password(payload.password)

    if incoming_hash != user_row["password_hash"]:
        conn.close()
        raise HTTPException(status_code=401, detail="invalid username or password")

    token = str(uuid4())

    cursor.execute(
        """
        INSERT INTO sessions (token, user_id, created_at)
        VALUES (?, ?, ?)
        """,
        (token, user_row["id"], datetime.utcnow().isoformat())
    )

    conn.commit()
    conn.close()

    user_info = UserInfo(
        id=user_row["id"],
        username=user_row["username"],
        role=user_row["role"]
    )

    return LoginResponse(token=token, user=user_info)


@app.get("/me", response_model=UserInfo)
def get_me(request: Request):
    authorization = request.headers.get("Authorization")
    user = get_current_user(authorization)

    return UserInfo(
        id=user["id"],
        username=user["username"],
        role=user["role"]
    )

@app.get("/my-appointments", response_model=List[Appointment])
def list_my_appointments(request: Request):
    user = get_current_user(request.headers.get("Authorization"))
    require_role(user, ["customer"])

    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute(
        'SELECT * FROM appointments WHERE customer_id = ? ORDER BY "start"',
        (user["id"],)
    ).fetchall()

    conn.close()

    return [Appointment(**dict(row)) for row in rows]


@app.post("/my-appointments", response_model=Appointment, status_code=201)
def create_my_appointment(payload: AppointmentCreate, request: Request):
    user = get_current_user(request.headers.get("Authorization"))
    require_role(user, ["customer"])

    if payload.end <= payload.start:
        raise HTTPException(status_code=400, detail="end must be after start")

    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute("SELECT * FROM appointments").fetchall()

    for row in rows:
        appt_start = datetime.fromisoformat(row["start"])
        appt_end = datetime.fromisoformat(row["end"])

        if overlaps(payload.start, payload.end, appt_start, appt_end):
            conn.close()
            raise HTTPException(
                status_code=409,
                detail="conflict: appointment time overlaps an existing appointment"
            )

    new_appt = Appointment(
        id=str(uuid4()),
        status="scheduled",
        customer_id=user["id"],
        **payload.model_dump()
    )

    cursor.execute(
        """
        INSERT INTO appointments (id, title, "start", "end", status, customer_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            new_appt.id,
            new_appt.title,
            new_appt.start.isoformat(),
            new_appt.end.isoformat(),
            new_appt.status,
            new_appt.customer_id
        )
    )

    conn.commit()
    conn.close()

    return new_appt


@app.patch("/my-appointments/{appointment_id}/cancel", response_model=Appointment)
def cancel_my_appointment(appointment_id: str, request: Request):
    user = get_current_user(request.headers.get("Authorization"))
    require_role(user, ["customer"])

    conn = get_connection()
    cursor = conn.cursor()

    row = cursor.execute(
        "SELECT * FROM appointments WHERE id = ? AND customer_id = ?",
        (appointment_id, user["id"])
    ).fetchone()

    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="appointment not found")

    if row["status"] == "cancelled":
        conn.close()
        raise HTTPException(status_code=400, detail="appointment is already cancelled")

    cursor.execute(
        "UPDATE appointments SET status = ? WHERE id = ?",
        ("cancelled", appointment_id)
    )
    conn.commit()

    updated_row = cursor.execute(
        "SELECT * FROM appointments WHERE id = ?",
        (appointment_id,)
    ).fetchone()

    conn.close()

    return Appointment(**dict(updated_row))


@app.patch("/my-appointments/{appointment_id}/reschedule", response_model=Appointment)
def reschedule_my_appointment(
    appointment_id: str,
    payload: AppointmentReschedule,
    request: Request
):
    user = get_current_user(request.headers.get("Authorization"))
    require_role(user, ["customer"])

    if payload.end <= payload.start:
        raise HTTPException(status_code=400, detail="end must be after start")

    conn = get_connection()
    cursor = conn.cursor()

    row = cursor.execute(
        "SELECT * FROM appointments WHERE id = ? AND customer_id = ?",
        (appointment_id, user["id"])
    ).fetchone()

    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="appointment not found")

    if row["status"] == "cancelled":
        conn.close()
        raise HTTPException(status_code=400, detail="cancelled appointments cannot be rescheduled")

    other_rows = cursor.execute(
        "SELECT * FROM appointments WHERE id != ?",
        (appointment_id,)
    ).fetchall()

    for other in other_rows:
        other_start = datetime.fromisoformat(other["start"])
        other_end = datetime.fromisoformat(other["end"])

        if overlaps(payload.start, payload.end, other_start, other_end):
            conn.close()
            raise HTTPException(
                status_code=409,
                detail="conflict: appointment time overlaps an existing appointment"
            )

    cursor.execute(
        'UPDATE appointments SET "start" = ?, "end" = ? WHERE id = ?',
        (
            payload.start.isoformat(),
            payload.end.isoformat(),
            appointment_id
        )
    )
    conn.commit()

    updated_row = cursor.execute(
        "SELECT * FROM appointments WHERE id = ?",
        (appointment_id,)
    ).fetchone()

    conn.close()

    return Appointment(**dict(updated_row))

@app.get("/employee/appointments", response_model=List[Appointment])
def list_all_appointments_for_employee(request: Request):
    user = get_current_user(request.headers.get("Authorization"))
    require_role(user, ["employee"])

    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute(
        'SELECT * FROM appointments ORDER BY "start"'
    ).fetchall()

    conn.close()

    return [Appointment(**dict(row)) for row in rows]


@app.patch("/employee/appointments/{appointment_id}/cancel", response_model=Appointment)
def cancel_appointment_as_employee(appointment_id: str, request: Request):
    user = get_current_user(request.headers.get("Authorization"))
    require_role(user, ["employee"])

    conn = get_connection()
    cursor = conn.cursor()

    row = cursor.execute(
        "SELECT * FROM appointments WHERE id = ?",
        (appointment_id,)
    ).fetchone()

    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="appointment not found")

    if row["status"] == "cancelled":
        conn.close()
        raise HTTPException(status_code=400, detail="appointment is already cancelled")

    cursor.execute(
        "UPDATE appointments SET status = ? WHERE id = ?",
        ("cancelled", appointment_id)
    )
    conn.commit()

    updated_row = cursor.execute(
        "SELECT * FROM appointments WHERE id = ?",
        (appointment_id,)
    ).fetchone()

    conn.close()

    return Appointment(**dict(updated_row))


@app.patch("/employee/appointments/{appointment_id}/reschedule", response_model=Appointment)
def reschedule_appointment_as_employee(
    appointment_id: str,
    payload: AppointmentReschedule,
    request: Request
):
    user = get_current_user(request.headers.get("Authorization"))
    require_role(user, ["employee"])

    if payload.end <= payload.start:
        raise HTTPException(status_code=400, detail="end must be after start")

    conn = get_connection()
    cursor = conn.cursor()

    row = cursor.execute(
        "SELECT * FROM appointments WHERE id = ?",
        (appointment_id,)
    ).fetchone()

    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="appointment not found")

    if row["status"] == "cancelled":
        conn.close()
        raise HTTPException(status_code=400, detail="cancelled appointments cannot be rescheduled")

    other_rows = cursor.execute(
        "SELECT * FROM appointments WHERE id != ?",
        (appointment_id,)
    ).fetchall()

    for other in other_rows:
        other_start = datetime.fromisoformat(other["start"])
        other_end = datetime.fromisoformat(other["end"])

        if overlaps(payload.start, payload.end, other_start, other_end):
            conn.close()
            raise HTTPException(
                status_code=409,
                detail="conflict: appointment time overlaps an existing appointment"
            )

    cursor.execute(
        'UPDATE appointments SET "start" = ?, "end" = ? WHERE id = ?',
        (
            payload.start.isoformat(),
            payload.end.isoformat(),
            appointment_id
        )
    )
    conn.commit()

    updated_row = cursor.execute(
        "SELECT * FROM appointments WHERE id = ?",
        (appointment_id,)
    ).fetchone()

    conn.close()

    return Appointment(**dict(updated_row))

@app.get("/employee/agent/insights")
def get_agent_insights(request: Request):
    user = get_current_user(request.headers.get("Authorization"))
    require_role(user, ["employee"])

    db_snapshot = get_latest_agent_snapshot_from_db()
    if db_snapshot is not None:
        return db_snapshot

    plan = load_json_if_exists(AGENT_PLAN_FILE)
    history = load_json_if_exists(AGENT_HISTORY_FILE)
    summary = load_text_if_exists(AGENT_SUMMARY_FILE)

    return {
        "plan": plan,
        "history": history,
        "summary": summary
    }

@app.post("/employee/agent/sync-db")
def sync_agent_files_to_db(request: Request):
    user = get_current_user(request.headers.get("Authorization"))
    require_role(user, ["employee"])

    plan = load_json_if_exists(AGENT_PLAN_FILE)
    history = load_json_if_exists(AGENT_HISTORY_FILE)
    summary = load_text_if_exists(AGENT_SUMMARY_FILE)

    if plan is None:
        raise HTTPException(status_code=404, detail="agent test plan file not found")

    build_run_id = save_agent_snapshot_to_db(plan, summary, history)

    return {
        "message": "agent snapshot saved to database",
        "build_run_id": build_run_id
    }

@app.get("/admin/agent/insights")
def get_admin_agent_insights(request: Request):
    user = get_current_user(request.headers.get("Authorization"))
    require_role(user, ["admin"])

    db_snapshot = get_latest_agent_snapshot_from_db()
    if db_snapshot is not None:
        return db_snapshot

    plan = load_json_if_exists(AGENT_PLAN_FILE)
    history = load_json_if_exists(AGENT_HISTORY_FILE)
    summary = load_text_if_exists(AGENT_SUMMARY_FILE)

    return {
        "plan": plan,
        "history": history,
        "summary": summary
    }


@app.post("/admin/agent/sync-db")
def sync_admin_agent_files_to_db(request: Request):
    user = get_current_user(request.headers.get("Authorization"))
    require_role(user, ["admin"])

    plan = load_json_if_exists(AGENT_PLAN_FILE)
    history = load_json_if_exists(AGENT_HISTORY_FILE)
    summary = load_text_if_exists(AGENT_SUMMARY_FILE)

    if plan is None:
        raise HTTPException(status_code=404, detail="agent test plan file not found")

    build_run_id = save_agent_snapshot_to_db(plan, summary, history)

    return {
        "message": "agent snapshot saved to database",
        "build_run_id": build_run_id
    }

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
            raise HTTPException(status_code=409, detail=f"conflict: appointment time overlaps an existing appointment")

    # Create a new appointment object with a generated UUID with an initial status of "scheduled"
    new_appt = Appointment(
        id=str(uuid4()),
        status="scheduled",
        customer_id=None,
        **payload.model_dump()
    )

    # Insert the new appointment into the SQLite database
    cursor.execute(
        """
        INSERT INTO appointments (id, title, "start", "end", status, customer_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            new_appt.id,
            new_appt.title,
            new_appt.start.isoformat(),
            new_appt.end.isoformat(),
            new_appt.status,
            new_appt.customer_id
        )
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
            raise HTTPException(status_code=409, detail=f"conflict: appointment time overlaps an existing appointment")

    # Update the appointment in the database
    cursor.execute(
        'UPDATE appointments SET "start" = ?, "end" = ? WHERE id = ?',
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