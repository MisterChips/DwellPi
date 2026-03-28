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

function applyDays(daysCsv) {
    var raw = String(daysCsv || "");
    var daysArr = raw.indexOf(",") >= 0 ? raw.split(",") : raw.split("");

    var wanted = {};
    daysArr.forEach(function (d) {
        var v = String(d).trim();
        if (v !== "") wanted[v] = true;
    });

    setChecked("day-mon", wanted["0"]);
    setChecked("day-tue", wanted["1"]);
    setChecked("day-wed", wanted["2"]);
    setChecked("day-thu", wanted["3"]);
    setChecked("day-fri", wanted["4"]);
    setChecked("day-sat", wanted["5"]);
    setChecked("day-sun", wanted["6"]);
}

function collectDays() {
    var out = [];
    if (document.getElementById("day-mon").checked) out.push("0");
    if (document.getElementById("day-tue").checked) out.push("1");
    if (document.getElementById("day-wed").checked) out.push("2");
    if (document.getElementById("day-thu").checked) out.push("3");
    if (document.getElementById("day-fri").checked) out.push("4");
    if (document.getElementById("day-sat").checked) out.push("5");
    if (document.getElementById("day-sun").checked) out.push("6");
    return out.join("");
}

function applyProgram(item) {
    setValue("prog-start", item.start_time || "");
    setValue("prog-end", item.end_time || "");
    setValue("prog-setpoint", item.setpoint != null ? item.setpoint : "");
    setValue("prog-note", item.note || "");

    applyDays(item.days);

    setValue("prog-warmup", item.warmup ? "on" : "off");
    setValue("prog-enabled", item.enabled ? "on" : "off");

    setText("chprogdetails-status-line", "Editing program #" + item.id);
}

function setNewProgramDefaults() {
    setValue("prog-start", "07:00");
    setValue("prog-end", "10:00");
    setValue("prog-setpoint", "19.5");
    setValue("prog-note", "");
    applyDays("0123456");
    setValue("prog-warmup", "off");
    setValue("prog-enabled", "on");
    setText("chprogdetails-status-line", "New heating program");
}

function collectProgramPayload() {
    return {
        system: "CH",
        schedule_set_name: "NORMAL",
        start_time: (document.getElementById("prog-start").value || "").trim(),
        end_time: (document.getElementById("prog-end").value || "").trim(),
        days: collectDays(),
        setpoint: (document.getElementById("prog-setpoint").value || "").trim(),
        warmup: document.getElementById("prog-warmup").value === "on",
        enabled: document.getElementById("prog-enabled").value === "on",
        note: (document.getElementById("prog-note").value || "").trim()
    };
}

function validateProgram(p) {
    if (!p.start_time) return "Start time is required";
    if (!p.end_time) return "End time is required";
    if (!p.days) return "Select at least one day";
    if (p.setpoint === "") return "Setpoint is required";

    var sp = parseFloat(p.setpoint);
    if (isNaN(sp)) return "Setpoint must be a number";

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
    }
    else{
        var copyBtn = document.getElementById("bt-prog-copy");
        if (copyBtn) copyBtn.disabled = false;

        var deleteBtn = document.getElementById("bt-prog-delete");
        if (deleteBtn) deleteBtn.disabled = false;
    }

    try {
        const r = await fetch("/api/ch/program?id=" + encodeURIComponent(id));
        const data = await r.json();

        if (!data.ok) {
            setText("chprogdetails-status-line", data.error || "Failed to load program");
            return;
        }

        applyProgram(data.item || {});
    } catch (e) {
        console.log("loadProgram failed", e);
        setText("chprogdetails-status-line", "Error loading program");
    }
}

async function saveProgram() {
    var id = qs("id");
    var payload = collectProgramPayload();
    var err = validateProgram(payload);

    if (err) {
        setText("chprogdetails-status-line", err);
        return;
    }

    try {
        setText("chprogdetails-status-line", id ? "Saving program..." : "Creating program...");

        var url = id ? "/api/ch/program/update" : "/api/ch/program/create";
        if (id) {
            payload.id = id;
        }

        const r = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const data = await r.json();

        if (!data.ok) {
            setText("chprogdetails-status-line", data.error || "Save failed");
            return;
        }

        if (!id && data.id) {
            window.location.href = "/web/chprogdetails.html?id=" + encodeURIComponent(data.id);
            return;
        }

        setText("chprogdetails-status-line", "Program saved");
        loadProgram();
    } catch (e) {
        console.log("saveProgram failed", e);
        setText("chprogdetails-status-line", "Error saving program");
    }
}

async function copyProgram() {
    var id = qs("id");
    if (!id) {
        setText("chprogdetails-status-line", "Save the new program before copying it");
        return;
    }

    try {
        setText("chprogdetails-status-line", "Copying program...");

        const r = await fetch("/api/ch/program/copy", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: id })
        });

        const data = await r.json();

        if (!data.ok) {
            setText("chprogdetails-status-line", data.error || "Copy failed");
            return;
        }

        if (data.id) {
            window.location.href = "/web/chprogdetails.html?id=" + encodeURIComponent(data.id);
            return;
        }

        setText("chprogdetails-status-line", "Program copied");
    } catch (e) {
        console.log("copyProgram failed", e);
        setText("chprogdetails-status-line", "Error copying program");
    }
}

async function deleteProgram() {
    var id = qs("id");
    if (!id) {
        setText("chprogdetails-status-line", "Nothing to delete yet");
        return;
    }

    if (!window.confirm("Delete this heating program?")) {
        return;
    }

    try {
        setText("chprogdetails-status-line", "Deleting program...");

        const r = await fetch("/api/ch/program/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: id })
        });

        const data = await r.json();

        if (!data.ok) {
            setText("chprogdetails-status-line", data.error || "Delete failed");
            return;
        }

        window.location.href = "/web/chprogs.html";
    } catch (e) {
        console.log("deleteProgram failed", e);
        setText("chprogdetails-status-line", "Error deleting program");
    }
}

window.addEventListener("DOMContentLoaded", function () {
    loadProgram();

    var cancelBtn = document.getElementById("bt-prog-cancel");
    if (cancelBtn) {
        cancelBtn.addEventListener("click", function () {
            window.location.href = "/web/chprogs.html";
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