function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
}

function setValue(id, value) {
    var el = document.getElementById(id);
    if (el) el.value = value;
}

function setSelectValue(id, value) {
    var el = document.getElementById(id);
    if (el) el.value = value;
}

function setEditableValue(id, value) {
    var el = document.getElementById(id);
    if (!el) return;

    if (value === undefined || value === null) {
        el.value = "";
        return;
    }

    el.value = String(value);
}

async function postSystemAction(url, confirmText) {
  if (!window.confirm(confirmText)) return;
  const r = await fetch(url, { method: "POST" });
  return await r.json();
}

function describeSetpointTarget(target) {
    if (!target) return "unknown";

    switch (target) {
        case "DEFAULT_ON_SETPOINT":
            return "Manual ON setpoint";
        case "BOOST_SETPOINT":
            return "Boost setpoint";
        case "PROGRAM":
            return "Active program";
        case "DEFAULT_SETPOINT":
            return "Default setpoint";
        default:
            return target;
    }
}

function getValue(id, fallback) {
    var el = document.getElementById(id);
    if (!el) return fallback;
    return el.value;
}

function bindClick(id, fn) {
    var el = document.getElementById(id);
    if (el) el.addEventListener("click", fn);
}

function bindChange(id, fn) {
    var el = document.getElementById(id);
    if (el) el.addEventListener("change", fn);
}

function postJson(url, payload) {
    return fetch(url, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(payload || {})
    }).then(function (r) {
        return r.json();
    });
}

function saveSetting(key, value) {
    return postJson("/api/settings/set", {
        key: key,
        value: value
    });
}

function saveLiveCHSetpoint(value) {
    return fetch("/api/ch/live_setpoint", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            value: value
        })
    }).then(function (r) {
        return r.json();
    });
}

function postBulkSettings(items) {
    return postJson("/api/settings/bulk", {
        items: items
    });
}

function delay(ms) {
    return new Promise(function (resolve) {
        setTimeout(resolve, ms);
    });
}

async function postAction(url, reloadFn, delayMs) {
    try {
        const r = await fetch(url, { method: "POST" });
        const data = await r.json();
        console.log(data);

        if (reloadFn) {
            await delay(delayMs || 500);
            await reloadFn();
        }

        return data;
    } catch (e) {
        console.log("postAction failed", e);
        return { ok: false, error: "Network error" };
    }
}

function changeNumberInput(id, delta) {
    var el = document.getElementById(id);
    if (!el) return;

    var current = parseFloat(el.value);
    if (isNaN(current)) current = 0;

    var step = parseFloat(el.step || "1");
    if (isNaN(step) || step <= 0) step = 1;

    var next = current + parseFloat(delta);

    if (!isNaN(parseFloat(el.min)) && next < parseFloat(el.min)) {
        next = parseFloat(el.min);
    }
    if (!isNaN(parseFloat(el.max)) && next > parseFloat(el.max)) {
        next = parseFloat(el.max);
    }

    var decimals = 0;
    if (String(step).indexOf(".") >= 0) {
        decimals = String(step).split(".")[1].length;
    }

    el.value = next.toFixed(decimals);

    // 🔥 THIS IS THE KEY BIT
    var event = new Event("change", { bubbles: true });
    el.dispatchEvent(event);
}