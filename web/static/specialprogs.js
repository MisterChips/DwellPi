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

function boolText(v) {
    if (v === true || v === 1 || String(v).toLowerCase() === "true") {
        return "On";
    }
    return "Off";
}

function textOrDash(v) {
    if (v === null || v === undefined || String(v).trim() === "") {
        return "--";
    }
    return escapeHtml(v);
}

function renderSpecialPrograms(items) {
    var tbody = document.getElementById("special-programs-tbody");
    if (!tbody) return;

    tbody.innerHTML = "";

    if (!items || !items.length) {
        var tr = document.createElement("tr");
        tr.innerHTML = '<td colspan="8">No special periods found.</td>';
        tbody.appendChild(tr);
        return;
    }

    items.forEach(function (item) {
        var tr = document.createElement("tr");

        tr.innerHTML =
            '<td><a href="/web/specialprogdetails.html?id=' + encodeURIComponent(item.id) + '">Edit</a></td>' +
            '<td>' + escapeHtml(String(item.id != null ? item.id : "--")) + '</td>' +
            '<td>' + textOrDash(item.start_ts_text) + '</td>' +
            '<td>' + textOrDash(item.end_ts_text) + '</td>' +
            '<td>' + textOrDash(item.systems) + '</td>' +
            '<td>' + textOrDash(item.schedule_set_name) + '</td>' +
            '<td>' + boolText(item.enabled) + '</td>' +
            '<td>' + textOrDash(item.note) + '</td>';

        tbody.appendChild(tr);
    });
}

async function loadSpecialPrograms() {
    try {
        setText("specialprogs-status-line", "Loading special periods...");

        const r = await fetch("/api/special/programs");
        const data = await r.json();

        if (!data.ok) {
            setText("specialprogs-status-line", data.error || "Failed to load special periods");
            return;
        }

        renderSpecialPrograms(data.items || []);
        setText("specialprogs-status-line", "Special periods loaded");
    } catch (e) {
        console.log("loadSpecialPrograms failed", e);
        setText("specialprogs-status-line", "Error loading special periods");
    }
}

window.addEventListener("DOMContentLoaded", function () {
    loadSpecialPrograms();

    var addBtn = document.getElementById("bt-specialprogs-add");
    if (addBtn) {
        addBtn.addEventListener("click", function () {
            window.location.href = "/web/specialprogdetails.html";
        });
    }
});