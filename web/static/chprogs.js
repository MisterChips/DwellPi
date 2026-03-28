function daysText(daysCsv) {
    if (!daysCsv) return "";

    var map = {
        "0": "Mon", "1": "Tue", "2": "Wed", "3": "Thu",
        "4": "Fri", "5": "Sat", "6": "Sun"
    };

    var rawStr = String(daysCsv).replace(/,/g, "");

    return rawStr
        .split("")
        .map(function (d) { return map[d] || ""; })
        .filter(function (x) { return x !== ""; })
        .join(" ");
}

function boolText(v) {
    if (v === true || v === 1 || String(v).toLowerCase() === "true") {
        return "On";
    }
    return "Off";
}

function noteText(v) {
    if (v === null || v === undefined || String(v).trim() === "") {
        return "--";
    }
    return String(v);
}

function setStatus(text) {
    var el = document.getElementById("chprogs-status-line");
    if (el) el.textContent = text;
}

function renderPrograms(items) {
    var tbody = document.getElementById("ch-programs-tbody");
    if (!tbody) return;

    tbody.innerHTML = "";

    if (!items || !items.length) {
        var tr = document.createElement("tr");
        tr.innerHTML = '<td colspan="8">No heating programs found.</td>';
        tbody.appendChild(tr);
        return;
    }

    items.forEach(function (item) {
        var tr = document.createElement("tr");

        tr.innerHTML =
            '<td><a href="/web/chprogdetails.html?id=' + item.id + '">Edit</a></td>' +
            '<td>' + (item.id != null ? item.id : "--") + '</td>' +
            '<td>' + (item.start_time || "--:--") + ' - ' + (item.end_time || "--:--") + '</td>' +
            '<td>' + daysText(item.days) + '</td>' +
            '<td>' + (item.setpoint != null ? item.setpoint : "--") + '</td>' +
            '<td>' + boolText(item.warmup) + '</td>' +
            '<td>' + boolText(item.enabled) + '</td>' +
            '<td>' + noteText(item.note) + '</td>';

        tbody.appendChild(tr);
    });
}

async function loadCHPrograms() {
    try {
        setStatus("Loading heating programs...");
        const r = await fetch("/api/ch/programs");
        const data = await r.json();

        if (!data.ok) {
            setStatus("Failed to load heating programs.");
            return;
        }

        renderPrograms(data.items || []);
        setStatus("Heating programs loaded.");
    } catch (e) {
        console.log("loadCHPrograms failed", e);
        setStatus("Error loading heating programs.");
    }
}

window.addEventListener("DOMContentLoaded", function () {
    var addBtn = document.getElementById("bt-chprogs-add");
    if (addBtn) {
        addBtn.addEventListener("click", function () {
            window.location.href = "/web/chprogdetails.html";
        });
    }

    loadCHPrograms();
});