const API_BASE_URL = "http://127.0.0.1:8000";

function saveSession(token, user) {
    localStorage.setItem("auth_token", token);
    localStorage.setItem("auth_user", JSON.stringify(user));
}

function getToken() {
    return localStorage.getItem("auth_token");
}

function getCurrentUser() {
    const raw = localStorage.getItem("auth_user");
    return raw ? JSON.parse(raw) : null;
}

function clearSession() {
    localStorage.removeItem("auth_token");
    localStorage.removeItem("auth_user");
}

function redirectByRole(user) {
    if (!user) {
        window.location.href = "login.html";
        return;
    }

    if (user.role === "customer") {
        window.location.href = "customer-dashboard.html";
    } else if (user.role === "employee") {
        window.location.href = "employee-dashboard.html";
    } else {
        window.location.href = "login.html";
    }
}

function requireAuth(expectedRole = null) {
    const token = getToken();
    const user = getCurrentUser();

    if (!token || !user) {
        window.location.href = "login.html";
        return null;
    }

    if (expectedRole && user.role !== expectedRole) {
        redirectByRole(user);
        return null;
    }

    return { token, user };
}

function logout() {
    clearSession();
    window.location.href = "login.html";
}