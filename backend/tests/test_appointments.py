from datetime import datetime
import httpx

BASE_URL = "http://127.0.0.1:8000"

def reset_backend_state():
    r = httpx.delete(f"{BASE_URL}/test/reset")
    assert r.status_code == 204

def test_create_appointment_success():
    reset_backend_state()
    payload = {"title": "Meeting", "start": "2026-02-23T10:00:00", "end": "2026-02-23T11:00:00",}
    r = httpx.post(f"{BASE_URL}/appointments", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert "id" in data
    assert data["title"] == "Meeting"

def test_list_appointments_returns_items():
    r = httpx.get(f"{BASE_URL}/appointments")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1  # should contain the appointment created earlier

def test_overlapping_appointment_rejected():
    payload = {"title": "Overlap", "start": "2026-02-23T10:30:00", "end": "2026-02-23T11:30:00",}
    r = httpx.post(f"{BASE_URL}/appointments", json=payload)
    assert r.status_code == 409

def test_invalid_time_range_rejected():
    payload = {"title": "BadTime", "start": "2026-02-23T12:00:00", "end": "2026-02-23T11:00:00",}
    r = httpx.post(f"{BASE_URL}/appointments", json=payload)
    assert r.status_code == 400