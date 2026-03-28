function qs(name) {
    var params = new URLSearchParams(window.location.search);
    return params.get(name);
}

function setValue(id, value) {
    var el = document.getElementById(id);
    if (el) el.value = value;
}

function setChecked(id, checked) {
    var el = document.getElementById(id);
    if (el) el.checked = !!checked;
}

function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
}

function toDateTimeLocalValue(value) {
    if (!value) return "";

    var s = String(value).trim();
    if (!s) return "";

    s = s.replace(" ", "T");
    if (s.length >= 16) return s.substring(0, 16);
    return s;
}

function systemsCsvFromChecks() {
    var out = [];
    if (document.getElementById("sys-ch").checked) out.push("CH");
    if (document.getElementById("sys-hw").checked) out.push("HW");
    return out.join(",");
}

function applySystemsCsv(csv) {
    var raw = String(csv || "").toUpperCase();
    var parts = raw.split(",");

    var wanted = {};
    parts.forEach(function (p) {
        var v = String(p).trim();
        if (v) wanted[v] = true;
    });

    setChecked("sys-ch", wanted["CH"]);
    setChecked("sys-hw", wanted["HW"]);
}

function dateTimeLocalToEpoch(text) {
    if (!text) return null;
    var d = new Date(text);
    if (isNaN(d.getTime())) return null;
    return Math.floor(d.getTime() / 1000);
}

function dateTimeLocalToText(text) {
    if (!text) return "";
    return String(text).replace("T", " ");
}

function applyProgram(item) {
    setValue("prog-start", toDateTimeLocalValue(item.start_ts_text || ""));
    setValue("prog-end", toDateTimeLocalValue(item.end_ts_text || ""));
    setValue("prog-note", item.note || "");
    setValue("prog-enabled", item.enabled ? "on" : "off");

    applySystemsCsv(item.systems || "");

    setText("holidayprogdetails-status-line", "Editing holiday period #" + item.id);
}

function setNewProgramDefaults() {
    setValue("prog-start", "");
    setValue("prog-end", "");
    setValue("prog-note", "");
    setValue("prog-enabled", "on");
    setChecked("sys-ch", true);
    setChecked("sys-hw", true);

    setText("holidayprogdetails-status-line", "New holiday period");
}

function collectProgramPayload() {
    var startText = (document.getElementById("prog-start").value || "").trim();
    var endText = (document.getElementById("prog-end").value || "").trim();

    return {
        start_ts_epoch: dateTimeLocalToEpoch(startText),
        start_ts_text: dateTimeLocalToText(startText),
        end_ts_epoch: dateTimeLocalToEpoch(endText),
        end_ts_text: dateTimeLocalToText(endText),
        systems: systemsCsvFromChecks(),
        enabled: document.getElementById("prog-enabled").value === "on",
        note: (document.getElementById("prog-note").value || "").trim()
    };
}

function validateProgram(p) {
    if (!p.start_ts_text) return "Start is required";
    if (!p.end_ts_text) return "End is required";
    if (p.start_ts_epoch == null) return "Start is invalid";
    if (p.end_ts_epoch == null) return "End is invalid";
    if (p.end_ts_epoch <= p.start_ts_epoch) return "End must be after start";
    if (!p.systems) return "Select at least one system";
    return null;
}

async function loadProgram() {
    var id = qs("id");
    if (!id) {
        setNewProgramDefaults();

        var copyBtn = document.getElementById("bt-prog-copy");
        if (copyBtn) copyBtn.disabled = true;

        var deleteBtn = document.getElementById("bt-prog-delete");
        if (deleteBtn) deleteBtn.disabled = true;
        return;
    } else {
        var copyBtn = document.getElementById("bt-prog-copy");
        if (copyBtn) copyBtn.disabled = false;

        var deleteBtn = document.getElementById("bt-prog-delete");
        if (deleteBtn) deleteBtn.disabled = false;
    }

    try {
        const r = await fetch("/api/holiday/program?id=" + encodeURIComponent(id));
        const data = await r.json();

        if (!data.ok) {
            setText("holidayprogdetails-status-line", data.error || "Failed to load holiday period");
            return;
        }

        applyProgram(data.item || {});
    } catch (e) {
        console.log("loadProgram failed", e);
        setText("holidayprogdetails-status-line", "Error loading holiday period");
    }
}

async function saveProgram() {
    var id = qs("id");
    var payload = collectProgramPayload();
    var err = validateProgram(payload);

    if (err) {
        setText("holidayprogdetails-status-line", err);
        return;
    }

    try {
        setText("holidayprogdetails-status-line", id ? "Saving holiday period..." : "Creating holiday period...");

        var url = id ? "/api/holiday/program/update" : "/api/holiday/program/create";
        if (id) payload.id = id;

        const r = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const data = await r.json();

        if (!data.ok) {
            setText("holidayprogdetails-status-line", data.error || "Save failed");
            return;
        }

        if (!id && data.id) {
            window.location.href = "/web/holidayprogdetails.html?id=" + encodeURIComponent(data.id);
            return;
        }

        setText("holidayprogdetails-status-line", "Holiday period saved");
        loadProgram();
    } catch (e) {
        console.log("saveProgram failed", e);
        setText("holidayprogdetails-status-line", "Error saving holiday period");
    }
}

async function copyProgram() {
    var id = qs("id");
    if (!id) {
        setText("holidayprogdetails-status-line", "Save the new holiday period before copying it");
        return;
    }

    try {
        setText("holidayprogdetails-status-line", "Copying holiday period...");

        const r = await fetch("/api/holiday/program/copy", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: id })
        });

        const data = await r.json();

        if (!data.ok) {
            setText("holidayprogdetails-status-line", data.error || "Copy failed");
            return;
        }

        if (data.id) {
            window.location.href = "/web/holidayprogdetails.html?id=" + encodeURIComponent(data.id);
            return;
        }

        setText("holidayprogdetails-status-line", "Holiday period copied");
    } catch (e) {
        console.log("copyProgram failed", e);
        setText("holidayprogdetails-status-line", "Error copying holiday period");
    }
}

async function deleteProgram() {
    var id = qs("id");
    if (!id) {
        setText("holidayprogdetails-status-line", "Nothing to delete yet");
        return;
    }

    if (!window.confirm("Delete this holiday period?")) {
        return;
    }

    try {
        setText("holidayprogdetails-status-line", "Deleting holiday period...");

        const r = await fetch("/api/holiday/program/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: id })
        });

        const data = await r.json();

        if (!data.ok) {
            setText("holidayprogdetails-status-line", data.error || "Delete failed");
            return;
        }

        window.location.href = "/web/holidayprogs.html";
    } catch (e) {
        console.log("deleteProgram failed", e);
        setText("holidayprogdetails-status-line", "Error deleting holiday period");
    }
}

window.addEventListener("DOMContentLoaded", function () {
    loadProgram();

    var cancelBtn = document.getElementById("bt-prog-cancel");
    if (cancelBtn) {
        cancelBtn.addEventListener("click", function () {
            window.location.href = "/web/holidayprogs.html";
        });
    }

    var saveBtn = document.getElementById("bt-prog-save");
    if (saveBtn) {
        saveBtn.addEventListener("click", function () {
            saveProgram();
        });
    }

    var copyBtn = document.getElementById("bt-prog-copy");
    if (copyBtn) {
        copyBtn.addEventListener("click", function () {
            copyProgram();
        });
    }

    var deleteBtn = document.getElementById("bt-prog-delete");
    if (deleteBtn) {
        deleteBtn.addEventListener("click", function () {
            deleteProgram();
        });
    }
});