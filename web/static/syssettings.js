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
            // No need to reload from server; the UI already has the values
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

        // Loop through your Master List to populate the UI
        ALL_SYSTEM_SETTINGS.forEach(item => {
            const val = settings[item.key];

            // Use the value from DB, or the default from our list, or an empty string
            const finalVal = (val !== undefined && val !== null)
                ? val
                : (item.default || "");

            setValue(item.id, finalVal);
        });

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

window.addEventListener("DOMContentLoaded", function () {
    loadSysSettingsStatus();
    loadSystemLoadInfo();
    loadRelayInfo();

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
});