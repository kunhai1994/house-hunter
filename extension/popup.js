async function loadState() {
  try {
    const state = await chrome.runtime.sendMessage({ type: "get_state" });
    document.getElementById("bridge").textContent = state.bridge || "—";
    document.getElementById("ext_id").textContent = (state.ext_id || "—").slice(0, 8);

    const logins = state.logged_in || {};
    const inOK = Object.entries(logins)
      .filter(([_, v]) => v === true)
      .map(([k]) => k);
    const inEl = document.getElementById("logins");
    if (inOK.length === 0) {
      inEl.innerHTML = '<span class="err">无</span>';
    } else {
      inEl.innerHTML = inOK.map(k => `<span class="ok">${k}</span>`).join(" · ");
    }

    const last = state.last_fetch_at;
    document.getElementById("last").textContent =
      last ? `${Math.round((Date.now() - last) / 1000)}s 前` : "未使用";

    const errs = state.consecutive_errors || 0;
    document.getElementById("errors").innerHTML =
      errs > 0 ? `<span class="err">${errs}</span>` : '<span class="ok">0</span>';
  } catch (e) {
    document.getElementById("logins").innerHTML = `<span class="err">SW 未响应: ${e.message}</span>`;
  }
}

document.getElementById("refresh").addEventListener("click", loadState);
loadState();
