function setStatus(text) {
    setText("statelog-status-line", text);
}

function todayIsoDate() {
    var d = new Date();
    var yyyy = d.getFullYear();
    var mm = String(d.getMonth() + 1).padStart(2, "0");
    var dd = String(d.getDate()).padStart(2, "0");
    return yyyy + "-" + mm + "-" + dd;
}

function renderStateLog(items) {
    var tbody = document.getElementById("statelog-tbody");
    if (!tbody) return;

    tbody.innerHTML = "";

    if (!items || !items.length) {
        var tr = document.createElement("tr");
        tr.innerHTML = '<td colspan="3">No state log entries found.</td>';
        tbody.appendChild(tr);
        return;
    }

    items.forEach(function (item) {
        var tr = document.createElement("tr");
        tr.innerHTML =
            "<td>" + (item.ts || "--") + "</td>" +
            "<td>" + (item.system || "--") + "</td>" +
            "<td>" + (item.state || "--") + "</td>";
        tbody.appendChild(tr);
    });
}

async function loadStateLog() {
    var dateEl = document.getElementById("statelog-date");
    var day = dateEl ? dateEl.value : "";

    try {
        setStatus("Loading state log...");
        var r = await fetch("/api/logs/state?date=" + encodeURIComponent(day));
        var data = await r.json();

        if (!data.ok) {
            setStatus(data.error || "Failed to load state log.");
            renderStateLog([]);
            return;
        }

        renderStateLog(data.items || []);
        setStatus("State log loaded for " + (data.date || day) + ".");
    } catch (e) {
        console.log("loadStateLog failed", e);
        setStatus("Error loading state log.");
        renderStateLog([]);
    }
}

window.addEventListener("DOMContentLoaded", function () {
    setValue("statelog-date", todayIsoDate());

    bindClick("bt-statelog-refresh", function () {
        loadStateLog();
    });

    bindChange("statelog-date", function () {
        loadStateLog();
    });

    loadStateLog();
});