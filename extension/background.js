/**
 * Housing Bridge — Background Service Worker
 *
 * 通过 HTTP long-poll 跟本地 bridge_server (localhost:9334) 通信。
 * 收到任务后用 chrome 的 fetch 抓目标 URL（自动带 cookie + 真 TLS 指纹），
 * 把 HTML 回报给 bridge。
 *
 * 设计要点：
 *   - HTTP polling 而非 WebSocket（service worker 不会因长 ws 闲置被杀）
 *   - chrome.alarms 25s 唤醒，防止 SW 被休眠
 *   - 每次 fetch 限速：跟 bridge 的速率限制双重保护
 *   - 每次心跳上报已登录的站点（用 cookie 探测）
 */

const BRIDGE = "http://localhost:9334";
const POLL_TIMEOUT_MS = 30000;         // long-poll 服务端最长挂 30s
const ERROR_BACKOFF_MS = 3000;         // 出错后 3s 再试
const HEARTBEAT_INTERVAL_MS = 15000;   // 心跳间隔
const FETCH_MIN_INTERVAL_MS = 2000;    // 两次 fetch 之间最小间隔

// 扩展实例 ID（每次 SW 启动随机生成）
const EXT_ID = crypto.randomUUID();

// 跟踪状态
let _running = true;
let _lastFetchAt = 0;
let _lastHeartbeatAt = 0;
let _consecutiveErrors = 0;

// 支持的房产站点（跟 manifest host_permissions 对应）
// 每个站点的 loginCookies = 必须存在的"登录态"cookie 名（白名单），
// 用来准确判断是否已登录（不依赖泛泛的 token/sid/user 关键字）
const SUPPORTED_DOMAINS = [
  {
    key: "lianjia", host: "lianjia.com",
    // 链家登录后必然有 lianjia_token，且 ucid 是用户 ID
    loginCookies: [/^lianjia_token$/i, /^ucid$/i, /^lianjia_uuid$/i, /^security_ticket$/i, /^lfrc_/i]
  },
  {
    key: "ke", host: "ke.com",
    // 贝壳跟链家共账号体系，cookie 名几乎相同
    loginCookies: [/^lianjia_token$/i, /^ke_token$/i, /^ucid$/i, /^security_ticket$/i]
  },
  {
    key: "ziroom", host: "ziroom.com",
    loginCookies: [/^ZIROOM_SSO_TOKEN$/i, /^ziroom_user/i, /^cuser$/i, /^uid_ziroom$/i]
  },
  {
    key: "anjuke", host: "anjuke.com",
    // anjuke 用 passport 系统
    loginCookies: [/^passportLogin58Sign$/i, /^aQQ_passport_/i, /^login_t$/i, /^58passport/i]
  },
  {
    key: "58", host: "58.com",
    loginCookies: [/^58cooper.*userid$/i, /^58login/i, /^webim.*token$/i, /^passport_/i]
  },
  {
    key: "fang", host: "fang.com",
    // 房天下用 Login_User_Name 等明确名字
    loginCookies: [/^login_user_name$/i, /^passport_sso$/i, /^global_username$/i, /^new_loginuser$/i]
  }
];

// ─────────────────────────── Service Worker 保活 ───────────────────────────
chrome.alarms.create("keepAlive", { periodInMinutes: 0.4 });  // ~25s
chrome.alarms.onAlarm.addListener(() => {
  // alarm 本身就唤醒了 SW；这里啥都不用做
});

// 扩展安装/启动时
chrome.runtime.onInstalled.addListener(() => {
  console.log("[Housing Bridge] installed");
  startPollLoop();
});
chrome.runtime.onStartup.addListener(() => {
  console.log("[Housing Bridge] startup");
  startPollLoop();
});

// SW 重新唤醒时自动跑
startPollLoop();

// ─────────────────────────── 主循环 ───────────────────────────
async function startPollLoop() {
  if (self._loopRunning) return;
  self._loopRunning = true;
  console.log("[Housing Bridge] poll loop started, ext_id=", EXT_ID);

  while (_running) {
    try {
      // 1. 周期性心跳
      if (Date.now() - _lastHeartbeatAt > HEARTBEAT_INTERVAL_MS) {
        await sendHeartbeat();
        _lastHeartbeatAt = Date.now();
      }

      // 2. long-poll 取任务
      const task = await pollTask();
      if (!task) continue;  // 204 no task

      // 3. 执行任务（限速）
      await rateLimit();
      const result = await executeFetch(task);

      // 4. 上报结果
      await postResult(task.task_id, result);

      _consecutiveErrors = 0;
    } catch (e) {
      _consecutiveErrors++;
      console.warn("[Housing Bridge] loop error:", e.message);
      // 指数退避（最多 30s）
      const backoff = Math.min(ERROR_BACKOFF_MS * Math.pow(1.5, _consecutiveErrors), 30000);
      await sleep(backoff);
    }
  }
  self._loopRunning = false;
}

// ─────────────────────────── HTTP helpers ───────────────────────────
async function pollTask() {
  const url = `${BRIDGE}/poll?ext_id=${EXT_ID}`;
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), POLL_TIMEOUT_MS + 5000);
  try {
    const r = await fetch(url, { signal: controller.signal });
    if (r.status === 204) return null;
    if (!r.ok) throw new Error(`poll ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(tid);
  }
}

async function postResult(taskId, payload) {
  await fetch(`${BRIDGE}/result`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId, ...payload })
  });
}

async function sendHeartbeat() {
  const loggedIn = await probeLogins();
  try {
    await fetch(`${BRIDGE}/heartbeat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ext_id: EXT_ID,
        logged_in: loggedIn,
        ts: Date.now()
      })
    });
  } catch (e) {
    // 心跳失败不致命，下一轮再试
  }
}

// ─────────────────────────── 执行 fetch 任务 ───────────────────────────
async function executeFetch(task) {
  const { url, timeout_ms = 15000 } = task;
  if (!url || !isUrlInScope(url)) {
    return { error: `URL out of scope: ${url}` };
  }
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), timeout_ms);
  try {
    const r = await fetch(url, {
      credentials: "include",
      redirect: "follow",
      signal: controller.signal
    });
    const html = await r.text();
    const finalUrl = r.url;
    const isLogin = looksLikeLoginPage(html, finalUrl);
    return {
      status: r.status,
      final_url: finalUrl,
      content_length: html.length,
      html: html,
      looks_like_login: isLogin
    };
  } catch (e) {
    return { error: `fetch failed: ${e.message}` };
  } finally {
    clearTimeout(tid);
  }
}

function isUrlInScope(url) {
  try {
    const u = new URL(url);
    return SUPPORTED_DOMAINS.some(d => u.host.endsWith(d.host));
  } catch {
    return false;
  }
}

function looksLikeLoginPage(html, finalUrl) {
  // 检测：登录页 / CAPTCHA / 风控拦截页
  if (!html) return true;
  if (html.length < 2000) return true;
  // URL 特征
  if (/login|passport|sso|signin|captcha|verify|antispam|shield/i.test(finalUrl)) return true;
  // 标题特征
  const titleMatch = html.match(/<title[^>]*>([^<]+)<\/title>/i);
  if (titleMatch) {
    const t = titleMatch[1].trim();
    if (/^(登录|登 录|请登录|账号登录|登录注册)\s*[\-—]?/.test(t)) return true;
    if (/captcha|verify|验证码|人机验证|安全验证|滑块验证|拼图验证/i.test(t)) return true;
    if (/^(403|404|访问受限|系统繁忙)/.test(t)) return true;
  }
  return false;
}

// ─────────────────────────── 限速 ───────────────────────────
async function rateLimit() {
  const elapsed = Date.now() - _lastFetchAt;
  if (elapsed < FETCH_MIN_INTERVAL_MS) {
    await sleep(FETCH_MIN_INTERVAL_MS - elapsed);
  }
  _lastFetchAt = Date.now();
}

// ─────────────────────────── 登录态探测 ───────────────────────────
async function probeLogins() {
  const result = {};
  await Promise.all(SUPPORTED_DOMAINS.map(async (d) => {
    try {
      const cookies = await chrome.cookies?.getAll({ domain: d.host });
      if (!cookies || cookies.length === 0) {
        result[d.key] = false;
        return;
      }
      // 站点特定 cookie 白名单 — 必须命中至少一个才算已登录
      const patterns = d.loginCookies || [];
      const isLoggedIn = cookies.some(c =>
        patterns.some(p => p.test(c.name))
      );
      result[d.key] = isLoggedIn;
    } catch {
      result[d.key] = null;  // 没 cookies 权限或异常
    }
  }));
  return result;
}

// ─────────────────────────── popup → background 消息（state 查询） ─────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === "get_state") {
    (async () => {
      const logins = await probeLogins();
      sendResponse({
        ext_id: EXT_ID,
        bridge: BRIDGE,
        logged_in: logins,
        last_fetch_at: _lastFetchAt,
        consecutive_errors: _consecutiveErrors
      });
    })();
    return true; // 异步响应
  }
});

// ─────────────────────────── util ───────────────────────────
function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}
