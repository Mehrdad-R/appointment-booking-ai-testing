const API_BASE_URL = "http://127.0.0.1:8000";

const form = document.getElementById("appointment-form");
const messageBox = document.getElementById("message-box");
const appointmentsList = document.getElementById("appointments-list");
const deleteAllBtn = document.getElementById("delete-all-btn");

// Track which appointment is currently being edited for rescheduling
let activeRescheduleId = null;

// Format ISO datetime strings into something more readable
function formatDateTime(dateTimeString) {
    const date = new Date(dateTimeString);
    return date.toLocaleString();
}

// Convert backend datetime string into datetime-local input format
function toDateTimeLocalValue(dateTimeString) {
    const date = new Date(dateTimeString);
    const offset = date.getTimezoneOffset();
    const localDate = new Date(date.getTime() - offset * 60000);
    return localDate.toISOString().slice(0, 16);
}

// Render the appointment list into the UI
function renderAppointments(appointments) {
    if (appointments.length === 0) {
        appointmentsList.innerHTML = `<p class="empty-state">No appointments scheduled yet.</p>`;
        return;
    }

    appointmentsList.innerHTML = appointments
        .map(appt => `
            <div class="appointment-card">
                <h3>${appt.title}</h3>
                <p><strong>Start:</strong> ${formatDateTime(appt.start)}</p>
                <p><strong>End:</strong> ${formatDateTime(appt.end)}</p>
                <p><strong>Status:</strong> <span class="status-badge">${appt.status}</span></p>

                <div class="appointment-actions">
                    ${appt.status !== "cancelled"
                        ? `
                            <button class="cancel-btn" onclick="cancelAppointment('${appt.id}')">Cancel</button>
                            <button class="reschedule-btn" onclick="openRescheduleForm('${appt.id}')">Reschedule</button>
                        `
                        : `<span class="cancelled-label">Already Cancelled</span>`
                    }
                </div>

                ${
                    activeRescheduleId === appt.id
                        ? `
                            <div class="reschedule-form">
                                <h4>Reschedule Appointment</h4>

                                <label for="reschedule-start-${appt.id}">New Start Time</label>
                                <input type="datetime-local" id="reschedule-start-${appt.id}" value="${toDateTimeLocalValue(appt.start)}">

                                <label for="reschedule-end-${appt.id}">New End Time</label>
                                <input type="datetime-local" id="reschedule-end-${appt.id}" value="${toDateTimeLocalValue(appt.end)}">

                                <div class="reschedule-actions">
                                    <button class="save-btn" onclick="submitReschedule('${appt.id}')">Save Reschedule</button>
                                    <button class="close-btn" onclick="closeRescheduleForm()">Close</button>
                                </div>
                            </div>
                        `
                        : ""
                }
            </div>
        `)
        .join("");
}

// Load appointments from the backend
async function loadAppointments() {
    try {
        const response = await fetch(`${API_BASE_URL}/appointments`);
        const data = await response.json();

        if (response.ok) {
            renderAppointments(data);
        } else {
            appointmentsList.innerHTML = `<p class="empty-state">Could not load appointments.</p>`;
        }
    } catch (error) {
        appointmentsList.innerHTML = `<p class="empty-state">Backend connection failed.</p>`;
    }
}

// Cancel an appointment by ID
async function cancelAppointment(appointmentId) {
    try {
        const response = await fetch(`${API_BASE_URL}/appointments/${appointmentId}/cancel`, {
            method: "PATCH"
        });

        const data = await response.json();

        if (response.ok) {
            messageBox.textContent = "Appointment cancelled successfully.";
            messageBox.style.color = "green";
            activeRescheduleId = null;
            loadAppointments();
        } else {
            messageBox.textContent = `Error: ${data.detail}`;
            messageBox.style.color = "red";
        }
    } catch (error) {
        messageBox.textContent = "Error: Could not connect to backend.";
        messageBox.style.color = "red";
    }
}

// Open inline reschedule form
function openRescheduleForm(appointmentId) {
    activeRescheduleId = appointmentId;
    loadAppointments();
}

// Close inline reschedule form
function closeRescheduleForm() {
    activeRescheduleId = null;
    loadAppointments();
}

// Submit reschedule request
async function submitReschedule(appointmentId) {
    const startInput = document.getElementById(`reschedule-start-${appointmentId}`);
    const endInput = document.getElementById(`reschedule-end-${appointmentId}`);

    const payload = {
        start: startInput.value,
        end: endInput.value
    };

    try {
        const response = await fetch(`${API_BASE_URL}/appointments/${appointmentId}/reschedule`, {
            method: "PATCH",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (response.ok) {
            messageBox.textContent = "Appointment rescheduled successfully.";
            messageBox.style.color = "green";
            activeRescheduleId = null;
            loadAppointments();
        } else {
            messageBox.textContent = `Error: ${data.detail}`;
            messageBox.style.color = "red";
        }
    } catch (error) {
        messageBox.textContent = "Error: Could not connect to backend.";
        messageBox.style.color = "red";
    }
}

// Delete all appointments from the backend
async function deleteAllAppointments() {
    const confirmed = confirm("Are you sure you want to delete all appointments?");
    if (!confirmed) return;

    try {
        const response = await fetch(`${API_BASE_URL}/test/reset`, {
            method: "DELETE"
        });

        if (response.status === 204) {
            messageBox.textContent = "All appointments were deleted successfully.";
            messageBox.style.color = "green";
            activeRescheduleId = null;
            loadAppointments();
        } else {
            messageBox.textContent = "Error: Could not delete appointments.";
            messageBox.style.color = "red";
        }
    } catch (error) {
        messageBox.textContent = "Error: Could not connect to backend.";
        messageBox.style.color = "red";
    }
}

// Handle form submission
form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const title = document.getElementById("title").value;
    const start = document.getElementById("start").value;
    const end = document.getElementById("end").value;

    const payload = {
        title: title,
        start: start,
        end: end
    };

    try {
        const response = await fetch(`${API_BASE_URL}/appointments`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (response.ok) {
            messageBox.textContent = `Appointment created successfully: ${data.title}`;
            messageBox.style.color = "green";
            form.reset();
            loadAppointments();
        } else {
            messageBox.textContent = `Error: ${data.detail}`;
            messageBox.style.color = "red";
        }
    } catch (error) {
        messageBox.textContent = "Error: Could not connect to backend.";
        messageBox.style.color = "red";
    }
});

deleteAllBtn.addEventListener("click", deleteAllAppointments);
// Load appointments when the page first opens
loadAppointments();
