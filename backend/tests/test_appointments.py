from pathlib import Path
import json

import httpx
import pytest

BASE_URL = "http://127.0.0.1:8000"


def reset_backend_state():
    r = httpx.delete(f"{BASE_URL}/test/reset")
    assert r.status_code == 204


def login(username: str, password: str):
    r = httpx.post(
        f"{BASE_URL}/login",
        json={"username": username, "password": password}
    )
    assert r.status_code == 200
    return r.json()


def auth_headers(token: str):
    return {"Authorization": f"Bearer {token}"}


def write_agent_artifacts():
    project_root = Path(__file__).resolve().parents[2]
    agent_dir = project_root / "backend" / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

    test_plan = {
        "decision_source": "gemini",
        "risk_level": "high",
        "selected_groups": ["smoke", "regression"],
        "priority_tests": [
            "test_create_appointment_success",
            "test_overlapping_appointment_rejected"
        ],
        "changed_files": ["backend/app.py"],
        "reason": "High-risk backend change."
    }

    history_runtime = {
        "recent_failures": [
            {
                "test_name": "test_overlapping_appointment_rejected",
                "failure_reason": "Conflict logic previously failed.",
                "module": "backend/app.py"
            }
        ],
        "slow_tests": [
            {
                "test_name": "test_reschedule_conflict_rejected",
                "estimated_runtime": "medium"
            }
        ],
        "high_risk_modules": ["backend/app.py"]
    }

    summary_text = """# AI Agent Decision Summary

## Decision Source
gemini

## Risk Level
high

## Selected Test Groups
smoke, regression

## Reasoning
High-risk backend change.
"""

    (agent_dir / "test_plan.json").write_text(
        json.dumps(test_plan, indent=2),
        encoding="utf-8"
    )
    (agent_dir / "history_runtime.json").write_text(
        json.dumps(history_runtime, indent=2),
        encoding="utf-8"
    )
    (agent_dir / "agent_decision_summary.md").write_text(
        summary_text,
        encoding="utf-8"
    )


@pytest.mark.smoke
def test_login_customer_success():
    reset_backend_state()
    data = login("customer1", "customer123")

    assert "token" in data
    assert data["user"]["username"] == "customer1"
    assert data["user"]["role"] == "customer"


@pytest.mark.smoke
def test_login_employee_success():
    reset_backend_state()
    data = login("employee1", "employee123")

    assert "token" in data
    assert data["user"]["username"] == "employee1"
    assert data["user"]["role"] == "employee"


@pytest.mark.regression
def test_login_invalid_credentials_rejected():
    r = httpx.post(
        f"{BASE_URL}/login",
        json={"username": "customer1", "password": "wrongpassword"}
    )
    assert r.status_code == 401


@pytest.mark.regression
def test_me_returns_logged_in_user():
    data = login("customer1", "customer123")
    token = data["token"]

    r = httpx.get(f"{BASE_URL}/me", headers=auth_headers(token))
    assert r.status_code == 200

    body = r.json()
    assert body["username"] == "customer1"
    assert body["role"] == "customer"


@pytest.mark.smoke
def test_create_my_appointment_success():
    reset_backend_state()
    data = login("customer1", "customer123")
    token = data["token"]

    payload = {
        "title": "Customer Meeting",
        "start": "2026-02-23T10:00:00",
        "end": "2026-02-23T11:00:00"
    }

    r = httpx.post(
        f"{BASE_URL}/my-appointments",
        json=payload,
        headers=auth_headers(token)
    )
    assert r.status_code == 201

    body = r.json()
    assert body["title"] == "Customer Meeting"
    assert body["status"] == "scheduled"
    assert body["customer_id"] == data["user"]["id"]


@pytest.mark.regression
def test_my_appointments_returns_only_the_logged_in_customers_appointments():
    reset_backend_state()

    customer1 = login("customer1", "customer123")
    customer2 = login("customer2", "customer234")

    token1 = customer1["token"]
    token2 = customer2["token"]

    payload1 = {
        "title": "Customer One Booking",
        "start": "2026-02-23T12:00:00",
        "end": "2026-02-23T13:00:00"
    }

    payload2 = {
        "title": "Customer Two Booking",
        "start": "2026-02-23T14:00:00",
        "end": "2026-02-23T15:00:00"
    }

    r1 = httpx.post(
        f"{BASE_URL}/my-appointments",
        json=payload1,
        headers=auth_headers(token1)
    )
    r2 = httpx.post(
        f"{BASE_URL}/my-appointments",
        json=payload2,
        headers=auth_headers(token2)
    )

    assert r1.status_code == 201
    assert r2.status_code == 201

    r_customer1 = httpx.get(
        f"{BASE_URL}/my-appointments",
        headers=auth_headers(token1)
    )
    r_customer2 = httpx.get(
        f"{BASE_URL}/my-appointments",
        headers=auth_headers(token2)
    )

    assert r_customer1.status_code == 200
    assert r_customer2.status_code == 200

    data1 = r_customer1.json()
    data2 = r_customer2.json()

    assert len(data1) == 1
    assert len(data2) == 1

    assert data1[0]["title"] == "Customer One Booking"
    assert data2[0]["title"] == "Customer Two Booking"

    assert data1[0]["customer_id"] == customer1["user"]["id"]
    assert data2[0]["customer_id"] == customer2["user"]["id"]


@pytest.mark.regression
def test_customer_cannot_cancel_another_customers_appointment():
    reset_backend_state()

    customer1 = login("customer1", "customer123")
    customer2 = login("customer2", "customer234")

    create_r = httpx.post(
        f"{BASE_URL}/my-appointments",
        json={
            "title": "Customer One Protected Appointment",
            "start": "2026-02-25T10:00:00",
            "end": "2026-02-25T11:00:00"
        },
        headers=auth_headers(customer1["token"])
    )
    assert create_r.status_code == 201

    appt_id = create_r.json()["id"]

    cancel_r = httpx.patch(
        f"{BASE_URL}/my-appointments/{appt_id}/cancel",
        headers=auth_headers(customer2["token"])
    )

    assert cancel_r.status_code == 404


@pytest.mark.regression
def test_customer_cannot_reschedule_another_customers_appointment():
    reset_backend_state()

    customer1 = login("customer1", "customer123")
    customer2 = login("customer2", "customer234")

    create_r = httpx.post(
        f"{BASE_URL}/my-appointments",
        json={
            "title": "Customer One Protected Reschedule",
            "start": "2026-02-25T12:00:00",
            "end": "2026-02-25T13:00:00"
        },
        headers=auth_headers(customer1["token"])
    )
    assert create_r.status_code == 201

    appt_id = create_r.json()["id"]

    reschedule_r = httpx.patch(
        f"{BASE_URL}/my-appointments/{appt_id}/reschedule",
        json={
            "start": "2026-02-25T14:00:00",
            "end": "2026-02-25T15:00:00"
        },
        headers=auth_headers(customer2["token"])
    )

    assert reschedule_r.status_code == 404


@pytest.mark.regression
def test_customer_cannot_access_employee_appointments():
    reset_backend_state()
    customer = login("customer1", "customer123")
    token = customer["token"]

    r = httpx.get(
        f"{BASE_URL}/employee/appointments",
        headers=auth_headers(token)
    )
    assert r.status_code == 403


@pytest.mark.regression
def test_employee_can_list_all_appointments():
    reset_backend_state()

    customer = login("customer1", "customer123")
    employee = login("employee1", "employee123")

    payload = {
        "title": "System Appointment",
        "start": "2026-02-23T16:00:00",
        "end": "2026-02-23T17:00:00"
    }

    create_r = httpx.post(
        f"{BASE_URL}/my-appointments",
        json=payload,
        headers=auth_headers(customer["token"])
    )
    assert create_r.status_code == 201

    r = httpx.get(
        f"{BASE_URL}/employee/appointments",
        headers=auth_headers(employee["token"])
    )
    assert r.status_code == 200

    data = r.json()
    assert len(data) >= 1
    assert any(item["title"] == "System Appointment" for item in data)


@pytest.mark.regression
def test_customer_can_cancel_own_appointment():
    reset_backend_state()
    customer = login("customer1", "customer123")
    token = customer["token"]

    create_r = httpx.post(
        f"{BASE_URL}/my-appointments",
        json={
            "title": "Cancelable Appointment",
            "start": "2026-02-23T18:00:00",
            "end": "2026-02-23T19:00:00"
        },
        headers=auth_headers(token)
    )
    assert create_r.status_code == 201
    appt_id = create_r.json()["id"]

    cancel_r = httpx.patch(
        f"{BASE_URL}/my-appointments/{appt_id}/cancel",
        headers=auth_headers(token)
    )
    assert cancel_r.status_code == 200
    assert cancel_r.json()["status"] == "cancelled"


@pytest.mark.regression
def test_customer_can_reschedule_own_appointment():
    reset_backend_state()
    customer = login("customer1", "customer123")
    token = customer["token"]

    create_r = httpx.post(
        f"{BASE_URL}/my-appointments",
        json={
            "title": "Reschedulable Appointment",
            "start": "2026-02-24T09:00:00",
            "end": "2026-02-24T10:00:00"
        },
        headers=auth_headers(token)
    )
    assert create_r.status_code == 201
    appt_id = create_r.json()["id"]

    reschedule_r = httpx.patch(
        f"{BASE_URL}/my-appointments/{appt_id}/reschedule",
        json={
            "start": "2026-02-24T11:00:00",
            "end": "2026-02-24T12:00:00"
        },
        headers=auth_headers(token)
    )
    assert reschedule_r.status_code == 200

    body = reschedule_r.json()
    assert body["start"].startswith("2026-02-24T11:00:00")
    assert body["end"].startswith("2026-02-24T12:00:00")


@pytest.mark.regression
def test_employee_can_cancel_any_appointment():
    reset_backend_state()
    customer = login("customer1", "customer123")
    employee = login("employee1", "employee123")

    create_r = httpx.post(
        f"{BASE_URL}/my-appointments",
        json={
            "title": "Employee Cancel Test",
            "start": "2026-02-24T13:00:00",
            "end": "2026-02-24T14:00:00"
        },
        headers=auth_headers(customer["token"])
    )
    assert create_r.status_code == 201
    appt_id = create_r.json()["id"]

    cancel_r = httpx.patch(
        f"{BASE_URL}/employee/appointments/{appt_id}/cancel",
        headers=auth_headers(employee["token"])
    )
    assert cancel_r.status_code == 200
    assert cancel_r.json()["status"] == "cancelled"


@pytest.mark.regression
def test_employee_can_reschedule_any_appointment():
    reset_backend_state()
    customer = login("customer1", "customer123")
    employee = login("employee1", "employee123")

    create_r = httpx.post(
        f"{BASE_URL}/my-appointments",
        json={
            "title": "Employee Reschedule Test",
            "start": "2026-02-24T15:00:00",
            "end": "2026-02-24T16:00:00"
        },
        headers=auth_headers(customer["token"])
    )
    assert create_r.status_code == 201
    appt_id = create_r.json()["id"]

    reschedule_r = httpx.patch(
        f"{BASE_URL}/employee/appointments/{appt_id}/reschedule",
        json={
            "start": "2026-02-24T17:00:00",
            "end": "2026-02-24T18:00:00"
        },
        headers=auth_headers(employee["token"])
    )
    assert reschedule_r.status_code == 200

    body = reschedule_r.json()
    assert body["start"].startswith("2026-02-24T17:00:00")
    assert body["end"].startswith("2026-02-24T18:00:00")


@pytest.mark.regression
def test_employee_can_sync_agent_snapshot_to_db():
    reset_backend_state()
    employee = login("employee1", "employee123")
    write_agent_artifacts()

    r = httpx.post(
        f"{BASE_URL}/employee/agent/sync-db",
        headers=auth_headers(employee["token"])
    )
    assert r.status_code == 200

    body = r.json()
    assert body["message"] == "agent snapshot saved to database"
    assert "build_run_id" in body


@pytest.mark.regression
def test_employee_can_view_agent_insights():
    reset_backend_state()
    employee = login("employee1", "employee123")
    write_agent_artifacts()

    sync_r = httpx.post(
        f"{BASE_URL}/employee/agent/sync-db",
        headers=auth_headers(employee["token"])
    )
    assert sync_r.status_code == 200

    r = httpx.get(
        f"{BASE_URL}/employee/agent/insights",
        headers=auth_headers(employee["token"])
    )
    assert r.status_code == 200

    body = r.json()
    assert "plan" in body
    assert "history" in body
    assert "summary" in body
    assert body["plan"]["risk_level"] == "high"