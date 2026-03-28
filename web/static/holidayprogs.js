function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
}

function escapeHtml(text) {
    return String(text == null ? "" : text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function renderHolidayPrograms(items) {
    var tbody = document.getElementById("holiday-programs-tbody");
    if (!tbody) return;

    tbody.innerHTML = "";

    if (!items || !items.length) {
        var tr = document.createElement("tr");
        tr.innerHTML = '<td colspan="7">No holiday periods found.</td>';
        tbody.appendChild(tr);
        return;
    }

    items.forEach(function (item) {
        var tr = document.createElement("tr");

        tr.innerHTML =
            '<td><a href="/web/holidayprogdetails.html?id=' + encodeURIComponent(item.id) + '">Edit</a></td>' +
            '<td>' + escapeHtml(item.id) + '</td>' +
            '<td>' + escapeHtml(item.start_ts_text || "") + '</td>' +
            '<td>' + escapeHtml(item.end_ts_text || "") + '</td>' +
            '<td>' + escapeHtml(item.systems || "") + '</td>' +
            '<td>' + (item.enabled ? "On" : "Off") + '</td>' +
            '<td>' + escapeHtml(item.note || "") + '</td>';

        tbody.appendChild(tr);
    });
}

async function loadHolidayPrograms() {
    try {
        setText("holidayprogs-status-line", "Loading holiday periods...");

        const r = await fetch("/api/holiday/programs");
        const data = await r.json();

        if (!data.ok) {
            setText("holidayprogs-status-line", data.error || "Failed to load holiday periods");
            return;
        }

        renderHolidayPrograms(data.items || []);
        setText("holidayprogs-status-line", "Holiday periods loaded");
    } catch (e) {
        console.log("loadHolidayPrograms failed", e);
        setText("holidayprogs-status-line", "Error loading holiday periods");
    }
}

window.addEventListener("DOMContentLoaded", function () {
    loadHolidayPrograms();

    var addBtn = document.getElementById("bt-holidayprogs-add");
    if (addBtn) {
        addBtn.addEventListener("click", function () {
            window.location.href = "/web/holidayprogdetails.html";
        });
    }
});