import httpx
import pytest

BASE_URL = "http://127.0.0.1:8000"

# Clear all appointments from the backend before each test scenario
def reset_backend_state():
    r = httpx.delete(f"{BASE_URL}/test/reset")
    assert r.status_code == 204

# Helper function to create an appointment and return the response
def create_sample_appointment(title="Meeting", start="2026-02-23T10:00:00", end="2026-02-23T11:00:00"):
    payload = {
        "title": title,
        "start": start,
        "end": end,
    }
    return httpx.post(f"{BASE_URL}/appointments", json=payload)

@pytest.mark.smoke
def test_create_appointment_success():
    # Verify that a valid appointment can be created successfully
    reset_backend_state()

    r = create_sample_appointment()
    assert r.status_code == 201

    data = r.json()
    assert "id" in data
    assert data["title"] == "Meeting"
    assert data["status"] == "scheduled"

@pytest.mark.smoke
def test_list_appointments_returns_items():
    # Verify that created appointments appear in the appointment list
    reset_backend_state()

    create_sample_appointment()

    r = httpx.get(f"{BASE_URL}/appointments")
    assert r.status_code == 200

    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["title"] == "Meeting"

@pytest.mark.regression
def test_get_appointment_by_id_returns_correct_item():
    # Verify that a specific appointment can be retrieved by ID
    reset_backend_state()

    create_response = create_sample_appointment()
    appointment_id = create_response.json()["id"]

    r = httpx.get(f"{BASE_URL}/appointments/{appointment_id}")
    assert r.status_code == 200

    data = r.json()
    assert data["id"] == appointment_id
    assert data["title"] == "Meeting"
    assert data["status"] == "scheduled"

@pytest.mark.regression
def test_overlapping_appointment_rejected():
    # Verify that overlapping appointments are rejected with HTTP 409
    reset_backend_state()

    create_sample_appointment()

    payload = {
        "title": "Overlap",
        "start": "2026-02-23T10:30:00",
        "end": "2026-02-23T11:30:00",
    }
    r = httpx.post(f"{BASE_URL}/appointments", json=payload)
    assert r.status_code == 409

@pytest.mark.regression
def test_invalid_time_range_rejected():
    # Verify that an appointment with an invalid time range is rejected
    reset_backend_state()

    payload = {
        "title": "BadTime",
        "start": "2026-02-23T12:00:00",
        "end": "2026-02-23T11:00:00",
    }
    r = httpx.post(f"{BASE_URL}/appointments", json=payload)
    assert r.status_code == 400

@pytest.mark.regression
def test_cancel_appointment_success():
    # Verify that a scheduled appointment can be cancelled
    reset_backend_state()

    create_response = create_sample_appointment()
    appointment_id = create_response.json()["id"]

    r = httpx.patch(f"{BASE_URL}/appointments/{appointment_id}/cancel")
    assert r.status_code == 200

    data = r.json()
    assert data["id"] == appointment_id
    assert data["status"] == "cancelled"

@pytest.mark.regression
def test_cancel_appointment_twice_rejected():
    # Verify that a cancelled appointment cannot be cancelled again
    reset_backend_state()

    create_response = create_sample_appointment()
    appointment_id = create_response.json()["id"]

    httpx.patch(f"{BASE_URL}/appointments/{appointment_id}/cancel")
    r = httpx.patch(f"{BASE_URL}/appointments/{appointment_id}/cancel")

    assert r.status_code == 400

@pytest.mark.regression
def test_reschedule_appointment_success():
    # Verify that a scheduled appointment can be moved to a new valid time
    reset_backend_state()

    create_response = create_sample_appointment()
    appointment_id = create_response.json()["id"]

    payload = {
        "start": "2026-02-23T12:00:00",
        "end": "2026-02-23T13:00:00",
    }

    r = httpx.patch(f"{BASE_URL}/appointments/{appointment_id}/reschedule", json=payload)
    assert r.status_code == 200

    data = r.json()
    assert data["start"] == "2026-02-23T12:00:00"
    assert data["end"] == "2026-02-23T13:00:00"

@pytest.mark.regression
def test_reschedule_conflict_rejected():
    # Verify that rescheduling into another appointment's time slot is rejected
    reset_backend_state()

    create_sample_appointment(title="Appointment 1", start="2026-02-23T10:00:00", end="2026-02-23T11:00:00")
    second_response = create_sample_appointment(title="Appointment 2", start="2026-02-23T12:00:00", end="2026-02-23T13:00:00")
    second_id = second_response.json()["id"]

    payload = {
        "start": "2026-02-23T10:30:00",
        "end": "2026-02-23T11:30:00",
    }

    r = httpx.patch(f"{BASE_URL}/appointments/{second_id}/reschedule", json=payload)
    assert r.status_code == 409