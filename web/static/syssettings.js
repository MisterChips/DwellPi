// A simple lock to prevent overlapping saves
var isSaving = false;

function setStatus(text) {
    setText("syssettings-status-line", text);
}

// Helper to build payload from a list of keys/IDs
function buildPayload(settingsList) {
    return settingsList.map(item => {
        return { key: item.key, value: getValue(item.id, item.default || "") };
    });
}

// Define the "Master List" of settings once
const ALL_SYSTEM_SETTINGS = [
    { key: "ENGINE_INTERVAL", id: "sys-engine-interval" },
    { key: "SENSOR_INTERVAL", id: "sys-sensor-interval" },
    { key: "LOGGING_INTERVAL", id: "sys-logging-interval" },
    { key: "RELAY_ENABLE", id: "sys-relay-enable", default: "False" },
    { key: "RELAY_BOARD_DEVICE_ID", id: "sys-relay-board-device-id" },
    { key: "CH_RELAY_LETTER", id: "sys-ch-relay-letter", default: "A" },
    { key: "HW_RELAY_LETTER", id: "sys-hw-relay-letter", default: "B" },
    { key: "SENSOR_DEVICE_ID", id: "sys-sensor-device-id" },
    { key: "LCD_BRIGHTNESS", id: "sys-lcd-brightness" },
    { key: "LCD_DIM_LEVEL", id: "sys-lcd-dim-level" },
    { key: "LCD_DIM_START_TIME", id: "sys-lcd-dim-start", default: "00:00" },
    { key: "LCD_DIM_END_TIME", id: "sys-lcd-dim-end", default: "00:00" }
];

async function saveSettings(onlyLcd = false) {
    if (isSaving) return;
    isSaving = true;

    // Filter the master list if we only want LCD settings
    const list = onlyLcd
        ? ALL_SYSTEM_SETTINGS.filter(s => s.key.startsWith("LCD_"))
        : ALL_SYSTEM_SETTINGS;

    setStatus(onlyLcd ? "Saving LCD settings..." : "Saving all settings...");

    try {
        const result = await postBulkSettings(buildPayload(list));
        if (result.ok) {
            setStatus("Settings saved successfully.");
        } else {
            setStatus("Save failed: " + (result.error || "unknown error"));
        }
    } catch (e) {
        setStatus("Network error during save.");
    } finally {
        isSaving = false;
    }
}

async function postSystemAction(url, pendingText, doneText) {
    setStatus(pendingText);

    try {
        const r = await fetch(url, { method: "POST" });
        const data = await r.json();

        if (data.ok) {
            setStatus(doneText);
        } else {
            setStatus("Action failed: " + (data.error || "unknown error"));
        }
    } catch (e) {
        console.log("system action failed", e);
        setStatus("Network error requesting system action.");
    }
}

async function loadSysSettingsStatus() {
    try {
        const r = await fetch("/api/status");
        const data = await r.json();

        if (!data.ok) {
            setStatus("Failed to load system settings");
            return;
        }

        const settings = data.settings || {};

        ALL_SYSTEM_SETTINGS.forEach(item => {
            const val = settings[item.key];
            const finalVal = (val !== undefined && val !== null)
                ? val
                : (item.default || "");

            setValue(item.id, finalVal);
        });
        updateSupervisorPanel(data.supervisor || {});

        setStatus("System settings loaded.");
    } catch (e) {
        console.log("loadSysSettingsStatus failed", e);
        setStatus("Error loading system settings");
    }
}

async function loadSystemLoadInfo() {
    try {
        const r = await fetch("/api/system/load");
        const data = await r.json();

        if (!data.ok) {
            setText("sys-info-uptime", "Uptime: --");
            setText("sys-info-loadavg", "Load Average: --");
            return;
        }

        setText("sys-info-uptime", data.uptime || "Uptime: --");
        setText("sys-info-loadavg", data.loadavg || "Load Average: --");
    } catch (e) {
        console.log("loadSystemLoadInfo failed", e);
        setText("sys-info-uptime", "Uptime: --");
        setText("sys-info-loadavg", "Load Average: --");
    }
}

function fmtRelayBool(v) {
    if (v === true) return "ON";
    if (v === false) return "OFF";
    return "--";
}

function clearRelayInfo(text) {
    setText("relay-info-device", "Device ID: " + (text || "--"));
    setText("relay-info-type", "Device Type: --");
    setText("relay-info-name", "Device Name: --");
    setText("relay-info-fw", "Firmware: --");
    setText("relay-info-llap", "LLAP Version: --");
    setText("relay-info-serial", "Serial: --");
    setText("relay-info-battery", "Battery: --");
    setText("relay-info-status", "Relay A/B: -- / --");
}

async function loadRelayInfo() {
    try {
        const r = await fetch("/api/relay/info");
        const data = await r.json();

        if (!data.ok) {
            clearRelayInfo("error");
            return;
        }

        const info = data.info || {};

        setText("relay-info-device", "Device ID: " + (info.device_id || "--"));
        setText("relay-info-type", "Device Type: " + (info.device_type || "--"));
        setText("relay-info-name", "Device Name: " + (info.device_name || "--"));
        setText("relay-info-fw", "Firmware: " + (info.firmware_version || "--"));
        setText("relay-info-llap", "LLAP Version: " + (info.llap_version || "--"));
        setText("relay-info-serial", "Serial: " + (info.serial_number || "--"));
        setText("relay-info-battery", "Battery: " + (info.battery_level || "--"));
        setText(
            "relay-info-status",
            "Relay A/B: " + fmtRelayBool(info.relay_a) + " / " + fmtRelayBool(info.relay_b)
        );
    } catch (e) {
        console.log("loadRelayInfo failed", e);
        clearRelayInfo("error");
    }
}

function fmtAgeSeconds(value) {
    if (value === null || value === undefined || isNaN(value)) return "--";
    return Math.round(Number(value)) + "s";
}

function fmtRestartCount(value) {
    if (value === null || value === undefined || isNaN(value)) return "0";
    return String(parseInt(value, 10));
}

function aliveText(flag) {
    return flag ? "UP" : "DN";
}

function dbReadyText(flag) {
    return flag ? "OK" : "WAIT";
}

async function loadSupervisorStatus() {
    try {
        const r = await fetch("/api/status");
        const data = await r.json();

        if (!data.ok) {
            setStatus("Failed to load supervisor status");
            return;
        }

        updateSupervisorPanel(data.supervisor || {});
    } catch (e) {
        console.log("loadSupervisorStatus failed", e);
        setStatus("Error loading supervisor status");
    }
}

function updateSupervisorPanel(wrapper) {
    var sup = (wrapper && wrapper.data) ? wrapper.data : {};
    var procs = sup.processes || {};

    var nowSec = Date.now() / 1000;
    var updatedAge = "--";
    var ts = parseFloat(sup.timestamp || 0);
    if (!isNaN(ts) && ts > 0) {
        updatedAge = fmtAgeSeconds(nowSec - ts);
    }

    setText("supervisor-mode", "Mode: " + (sup.mode || "--"));
    setText("supervisor-db-ready", "DB Ready: " + dbReadyText(!!sup.db_ready));
    setText("supervisor-updated-age", "Last Update: " + updatedAge);

    function processSummary(name, p) {
        p = p || {};
        return (
            name +
            ": " + aliveText(!!p.alive) +
            " | hb " + fmtAgeSeconds(p.heartbeat_age) +
            " | restarts " + fmtRestartCount(p.restart_count)
        );
    }

    setText("supervisor-engine", processSummary("Engine", procs.engine));
    setText("supervisor-sensor", processSummary("Sensor", procs.sensor));
    setText("supervisor-relay", processSummary("Relay", procs.relay));
    setText("supervisor-ui", processSummary("UI", procs.ui));
    setText("supervisor-web", processSummary("Web", procs.web));

    var db = procs.db || {};
    setText(
        "supervisor-db",
        "DB: " + aliveText(!!db.alive) +
        " | restarts " + fmtRestartCount(db.restart_count)
    );
}

async function restartProcess(name) {
    setStatus("Requesting " + name + " restart...");

    try {
        const r = await fetch("/api/system/restart_process", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name })
        });

        const data = await r.json();

        if (data.ok) {
            if (data.was_running === false) {
                setStatus(name + " was already stopped. Started fresh.");
            } else {
                setStatus(name + " restarted.");
            }
            setTimeout(loadSupervisorStatus, 1000);
        } else {
            setStatus("Restart failed: " + (data.error || "unknown error"));
        }
    } catch (e) {
        console.log("restartProcess failed", e);
        setStatus("Network error requesting process restart.");
    }
}

window.addEventListener("DOMContentLoaded", function () {
    loadSysSettingsStatus();
    loadSystemLoadInfo();
    loadRelayInfo();
    setInterval(loadSupervisorStatus, 5000);

    bindClick("bt-syssettings-save", () => saveSettings(false));
    bindClick("bt-save-lcd-settings", () => saveSettings(true));

    // Stepper Button Setup
    document.querySelectorAll(".stepper-btn").forEach(btn => {
        btn.addEventListener("click", function () {
            changeNumberInput(this.getAttribute("data-target"), this.getAttribute("data-step"));
        });
    });

    // Refresh Buttons
    bindClick("bt-refresh-system-load", async () => {
        setStatus("Refreshing Pi load...");
        await loadSystemLoadInfo();
        setStatus("Pi load refreshed.");
    });

    bindClick("bt-refresh-relay-info", async () => {
        setStatus("Refreshing RelayBoard info...");
        await loadRelayInfo();
        setStatus("RelayBoard info refreshed.");
    });

    // RESTART Buttons
   bindClick("bt-restart-dwellpi", async () => {
        if (!window.confirm("Restart DwellPi now?")) return;
        await postSystemAction("/api/system/restart_dwellpi", "Requesting DwellPi restart...", "DwellPi restart requested.");
    });

    bindClick("bt-reboot-pi", async () => {
        if (!window.confirm("Reboot Raspberry Pi now?")) return;
        await postSystemAction("/api/system/reboot_pi", "Requesting Raspberry Pi reboot...", "Raspberry Pi reboot requested.");
    });

    bindClick("bt-refresh-supervisor", async () => {
        setStatus("Refreshing supervisor status...");
        await loadSupervisorStatus();
        setStatus("Supervisor status refreshed.");
    });

    bindClick("bt-restart-engine", async () => {
        if (!window.confirm("Restart Engine now?")) return;
        await restartProcess("engine");
    });

    bindClick("bt-restart-sensor", async () => {
        if (!window.confirm("Restart Sensor now?")) return;
        await restartProcess("sensor");
    });

    bindClick("bt-restart-relay", async () => {
        if (!window.confirm("Restart Relay now?")) return;
        await restartProcess("relay");
    });

    bindClick("bt-restart-ui", async () => {
        if (!window.confirm("Restart UI now?")) return;
        await restartProcess("ui");
    });

    bindClick("bt-restart-web", async () => {
        if (!window.confirm("Restart Web now?")) return;
        await restartProcess("web");
    });
});