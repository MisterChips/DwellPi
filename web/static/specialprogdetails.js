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

function populateScheduleSets(items, selected) {
    var sel = document.getElementById("prog-schedule-set");
    if (!sel) return;

    sel.innerHTML = "";

    var seen = {};
    var values = [];

    (items || []).forEach(function (item) {
        var name = item && item.name != null ? String(item.name) : "";
        if (!name || seen[name]) return;
        seen[name] = true;
        values.push(name);
    });

    if (!seen["NORMAL"]) {
        values.unshift("NORMAL");
    }

    values.forEach(function (name) {
        var opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        sel.appendChild(opt);
    });

    sel.value = selected || "NORMAL";
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
    setValue("prog-schedule-set", item.schedule_set_name || "");

    setText("specialprogdetails-status-line", "Editing special period #" + item.id);
}

function setNewProgramDefaults() {
    setValue("prog-start", "");
    setValue("prog-end", "");
    setValue("prog-note", "");
    setValue("prog-enabled", "on");
    setChecked("sys-ch", true);
    setChecked("sys-hw", false);

    setText("specialprogdetails-status-line", "New special period");
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
        schedule_set_name: (document.getElementById("prog-schedule-set").value || "").trim(),
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
    if (!p.schedule_set_name) return "Schedule set is required";
    if (p.schedule_set_name === "NORMAL") return "NORMAL cannot be used for a special period";
    return null;
}

async function loadScheduleSets(selected) {
    try {
        const r = await fetch("/api/schedule_sets");
        const data = await r.json();

        if (data.ok) {
            populateScheduleSets(data.items || [], selected || "");
        } else {
            populateScheduleSets([], selected || "");
        }
    } catch (e) {
        console.log("loadScheduleSets failed", e);
        populateScheduleSets([], selected || "");
    }
}

async function loadProgram() {
    var id = qs("id");

    if (!id) {
        await loadScheduleSets("");
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
        const r = await fetch("/api/special/program?id=" + encodeURIComponent(id));
        const data = await r.json();

        if (!data.ok) {
            setText("specialprogdetails-status-line", data.error || "Failed to load special period");
            return;
        }

        var item = data.item || {};
        await loadScheduleSets(item.schedule_set_name || "");
        applyProgram(item);
    } catch (e) {
        console.log("loadProgram failed", e);
        setText("specialprogdetails-status-line", "Error loading special period");
    }
}

async function saveProgram() {
    var id = qs("id");
    var payload = collectProgramPayload();
    var err = validateProgram(payload);

    if (err) {
        setText("specialprogdetails-status-line", err);
        return;
    }

    try {
        setText("specialprogdetails-status-line", id ? "Saving special period..." : "Creating special period...");

        var url = id ? "/api/special/program/update" : "/api/special/program/create";
        if (id) payload.id = id;

        const r = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const data = await r.json();

        if (!data.ok) {
            setText("specialprogdetails-status-line", data.error || "Save failed");
            return;
        }

        if (!id && data.id) {
            window.location.href = "/web/specialprogdetails.html?id=" + encodeURIComponent(data.id);
            return;
        }

        setText("specialprogdetails-status-line", "Special period saved");
        loadProgram();
    } catch (e) {
        console.log("saveProgram failed", e);
        setText("specialprogdetails-status-line", "Error saving special period");
    }
}

async function copyProgram() {
    var id = qs("id");
    if (!id) {
        setText("specialprogdetails-status-line", "Save the new special period before copying it");
        return;
    }

    try {
        setText("specialprogdetails-status-line", "Copying special period...");

        const r = await fetch("/api/special/program/copy", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: id })
        });

        const data = await r.json();

        if (!data.ok) {
            setText("specialprogdetails-status-line", data.error || "Copy failed");
            return;
        }

        if (data.id) {
            window.location.href = "/web/specialprogdetails.html?id=" + encodeURIComponent(data.id);
            return;
        }

        setText("specialprogdetails-status-line", "Special period copied");
    } catch (e) {
        console.log("copyProgram failed", e);
        setText("specialprogdetails-status-line", "Error copying special period");
    }
}

async function deleteProgram() {
    var id = qs("id");
    if (!id) {
        setText("specialprogdetails-status-line", "Nothing to delete yet");
        return;
    }

    if (!window.confirm("Delete this special period?")) {
        return;
    }

    try {
        setText("specialprogdetails-status-line", "Deleting special period...");

        const r = await fetch("/api/special/program/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: id })
        });

        const data = await r.json();

        if (!data.ok) {
            setText("specialprogdetails-status-line", data.error || "Delete failed");
            return;
        }

        window.location.href = "/web/specialprogs.html";
    } catch (e) {
        console.log("deleteProgram failed", e);
        setText("specialprogdetails-status-line", "Error deleting special period");
    }
}

window.addEventListener("DOMContentLoaded", function () {
    loadProgram();

    var cancelBtn = document.getElementById("bt-prog-cancel");
    if (cancelBtn) {
        cancelBtn.addEventListener("click", function () {
            window.location.href = "/web/specialprogs.html";
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