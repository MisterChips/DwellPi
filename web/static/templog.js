function setStatus(text) {
    setText("templog-status-line", text);
}

function todayIsoDate() {
    var d = new Date();
    var yyyy = d.getFullYear();
    var mm = String(d.getMonth() + 1).padStart(2, "0");
    var dd = String(d.getDate()).padStart(2, "0");
    return yyyy + "-" + mm + "-" + dd;
}

function renderTempLog(items) {
    var tbody = document.getElementById("templog-tbody");
    if (!tbody) return;

    tbody.innerHTML = "";

    if (!items || !items.length) {
        var tr = document.createElement("tr");
        tr.innerHTML = '<td colspan="3">No temperature log entries found.</td>';
        tbody.appendChild(tr);
        return;
    }

    items.forEach(function (item) {
        var valueText = (item.value === null || item.value === undefined) ? "--" : String(item.value);

        var tr = document.createElement("tr");
        tr.innerHTML =
            "<td>" + (item.ts || "--") + "</td>" +
            "<td>" + (item.source || "--") + "</td>" +
            "<td>" + valueText + " C</td>";
        tbody.appendChild(tr);
    });
}

async function loadTempLog() {
    var dateEl = document.getElementById("templog-date");
    var day = dateEl ? dateEl.value : "";

    try {
        setStatus("Loading temperature log...");
        var r = await fetch("/api/logs/temp?date=" + encodeURIComponent(day));
        var data = await r.json();

        if (!data.ok) {
            setStatus(data.error || "Failed to load temperature log.");
            renderTempLog([]);
            return;
        }

        renderTempLog(data.items || []);
        setStatus("Temperature log loaded for " + (data.date || day) + ".");
    } catch (e) {
        console.log("loadTempLog failed", e);
        setStatus("Error loading temperature log.");
        renderTempLog([]);
    }
}

window.addEventListener("DOMContentLoaded", function () {
    setValue("templog-date", todayIsoDate());

    bindClick("bt-templog-refresh", function () {
        loadTempLog();
    });

    bindChange("templog-date", function () {
        loadTempLog();
    });

    loadTempLog();
});