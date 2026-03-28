// Grace Period Tracking
var lastManualSwitchTime = 0;   // Timed/On/Off switch
var lastManualAdvanceTime = 0;  // Advance button

function getBoostRemainingSeconds(finishEpoch) {
    var nowSec = Math.floor(Date.now() / 1000);
    var finish = parseInt(finishEpoch || 0, 10);
    if (isNaN(finish)) finish = 0;
    return Math.max(0, finish - nowSec);
}

function refreshBoostButtons(finishEpoch, plusBtnId, clearBtnId) {
    var plusBtn = document.getElementById(plusBtnId);
    var clearBtn = document.getElementById(clearBtnId);

    if (!plusBtn || !clearBtn) return;

    var remaining = getBoostRemainingSeconds(finishEpoch);
    var active = remaining > 0;
    var atMax = remaining >= (3 * 3600);

    if (!active) {
        plusBtn.textContent = "1 Hour";
        plusBtn.style.display = "";
        clearBtn.disabled = true;
        return;
    }

    clearBtn.disabled = false;

    if (atMax) {
        plusBtn.style.display = "none";
    } else {
        plusBtn.style.display = "";
        plusBtn.textContent = "+ Hour";
    }
}

async function loadHWSettingsStatus() {
    try {
        var r = await fetch("/api/status");
        var data = await r.json();
        if (!data.ok) return;

        var s = data.state || {};
        var cfg = data.settings || {};
        var now = Date.now();
        var gracePeriod = 5000;

        setText("water-demand-status", s.hw_desired || "--");
        setValue("ip-hwsettings-water-boost", cfg.HW_BOOST_FINISH_TIME || "00:00");

        refreshBoostButtons(
            cfg.HW_BOOST_FINISH_EPOCH,
            "bt-hwsettings-water-boost-plus",
            "bt-hwsettings-water-boost-clear"
        );

        setText("water-programs-status", s.hw_reason || "--");

        if ((now - lastManualSwitchTime) > gracePeriod) {
            setSelectValue(
                "sel-hwsettings-water-switch",
                (s.hw_switch || cfg.HW_SYSTEM_SWITCH || "timed").toLowerCase()
            );
        }

        var advBtn = document.getElementById("bt-hwsettings-water-advance");
        if (advBtn && (now - lastManualAdvanceTime) > gracePeriod) {
            if (s.hw_advance || cfg.HW_ADVANCE === "True") {
                advBtn.classList.add("active");
            } else {
                advBtn.classList.remove("active");
            }
        }

    } catch (e) {
        console.log("loadHWSettingsStatus failed", e);
    }
}

window.addEventListener("DOMContentLoaded", function () {
    bindClick("bt-hwsettings-water-advance", function () {
        lastManualAdvanceTime = Date.now();
        this.classList.toggle("active");
        postAction("/api/hw/advance", loadHWSettingsStatus);
    });

    bindChange("sel-hwsettings-water-switch", function (e) {
        lastManualSwitchTime = Date.now();

        saveSetting("HW_SYSTEM_SWITCH", e.target.value)
            .then(function (res) {
                if (res && res.ok) {
                    return loadHWSettingsStatus();
                } else {
                    lastManualSwitchTime = 0;
                }
            })
            .catch(function (err) {
                console.log("HW switch save failed", err);
                lastManualSwitchTime = 0;
            });
    });

    bindClick("bt-hwsettings-water-boost-plus", function () {
        postAction("/api/hw/boost?mins=60", loadHWSettingsStatus);
    });

    bindClick("bt-hwsettings-water-boost-clear", function () {
        postAction("/api/hw/boost?mins=0", loadHWSettingsStatus);
    });

    loadHWSettingsStatus();
    setInterval(loadHWSettingsStatus, 3000);
});