/*!
 * AI Receptionist chat widget.
 * Вставка на будь-який сайт:
 *   <script src="https://YOUR-API/widget.js"
 *           data-business="Skyline Realty" data-niche="real_estate"
 *           data-color="#2563eb" data-phone="+15551234567"
 *           data-greeting="Вітаю! Допоможу підібрати квартиру і записати на перегляд."></script>
 */
(function () {
  var script = document.currentScript || document.querySelector('script[src*="widget.js"]');
  var ds = (script && script.dataset) || {};
  var cfg = window.AIReceptionistConfig || {};
  function opt(k, d) { return cfg[k] || ds[k] || d; }

  var API = opt("api", script ? new URL(script.src).origin : "");
  var BUSINESS = opt("business", "");
  var NICHE = opt("niche", "real_estate");
  var COLOR = opt("color", "#2563eb");
  var PHONE = opt("phone", "");
  var GREETING = opt("greeting", "Вітаю! 👋 Я AI-адміністратор" + (BUSINESS ? " «" + BUSINESS + "»" : "") + ". Допоможу записатися — що вас цікавить?");
  var OPEN = opt("open", "") === "true";
  var SKEY = "air_sid_" + (BUSINESS || NICHE);

  var css = "" +
    ".air-btn{position:fixed;right:20px;bottom:20px;width:60px;height:60px;border-radius:50%;border:0;cursor:pointer;background:" + COLOR + ";color:#fff;font-size:26px;box-shadow:0 8px 24px rgba(0,0,0,.25);z-index:2147483000;transition:transform .15s}" +
    ".air-btn:hover{transform:scale(1.07)}" +
    ".air-win{position:fixed;right:20px;bottom:92px;width:370px;max-width:calc(100vw - 32px);height:560px;max-height:calc(100vh - 120px);background:#fff;border-radius:16px;box-shadow:0 16px 48px rgba(0,0,0,.25);display:none;flex-direction:column;overflow:hidden;z-index:2147483000;font:14px/1.45 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#111}" +
    ".air-win.open{display:flex}" +
    ".air-head{background:" + COLOR + ";color:#fff;padding:14px 16px;display:flex;align-items:center;gap:10px}" +
    ".air-head b{display:block;font-size:15px}.air-head small{opacity:.85}" +
    ".air-dot{width:9px;height:9px;border-radius:50%;background:#4ade80;box-shadow:0 0 0 3px rgba(74,222,128,.3)}" +
    ".air-x{margin-left:auto;background:none;border:0;color:#fff;font-size:22px;cursor:pointer}" +
    ".air-msgs{flex:1;overflow-y:auto;padding:14px;background:#f6f7f9;display:flex;flex-direction:column;gap:8px}" +
    ".air-m{max-width:82%;padding:9px 12px;border-radius:14px;white-space:pre-wrap;word-wrap:break-word}" +
    ".air-m.bot{background:#fff;border:1px solid #e5e7eb;align-self:flex-start;border-bottom-left-radius:4px}" +
    ".air-m.me{background:" + COLOR + ";color:#fff;align-self:flex-end;border-bottom-right-radius:4px}" +
    ".air-typing{align-self:flex-start;color:#6b7280;font-size:13px;padding:4px 8px}" +
    ".air-call{display:block;margin:0 14px 10px;padding:9px;border-radius:10px;text-align:center;background:#111;color:#fff;text-decoration:none;font-weight:600}" +
    ".air-form{display:flex;gap:8px;padding:10px;border-top:1px solid #e5e7eb;background:#fff}" +
    ".air-form input{flex:1;border:1px solid #d1d5db;border-radius:10px;padding:10px 12px;font:inherit;outline:none}" +
    ".air-form input:focus{border-color:" + COLOR + "}" +
    ".air-form button{border:0;border-radius:10px;padding:0 16px;background:" + COLOR + ";color:#fff;font-weight:600;cursor:pointer}" +
    ".air-form button:disabled{opacity:.5}" +
    ".air-foot{text-align:center;font-size:11px;color:#9ca3af;padding:0 0 8px;background:#fff}";
  var st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

  var btn = document.createElement("button");
  btn.className = "air-btn"; btn.setAttribute("aria-label", "Відкрити чат"); btn.textContent = "💬";
  var win = document.createElement("div");
  win.className = "air-win";
  win.innerHTML =
    '<div class="air-head"><span class="air-dot"></span><div><b></b><small>AI-адміністратор · відповідає миттєво</small></div><button class="air-x" aria-label="Закрити">×</button></div>' +
    '<div class="air-msgs"></div>' +
    (PHONE ? '<a class="air-call" href="tel:' + PHONE + '">📞 Або зателефонуйте AI: ' + PHONE + '</a>' : "") +
    '<form class="air-form"><input placeholder="Напишіть повідомлення…" maxlength="2000" /><button>➤</button></form>' +
    '<div class="air-foot">Powered by AI Receptionist</div>';
  win.querySelector(".air-head b").textContent = BUSINESS || "Онлайн-запис";
  document.body.appendChild(win); document.body.appendChild(btn);

  var msgs = win.querySelector(".air-msgs");
  var form = win.querySelector("form");
  var input = form.querySelector("input");
  var send = form.querySelector("button");
  var sid = null;
  try { sid = sessionStorage.getItem(SKEY); } catch (e) {}

  function add(text, who) {
    var d = document.createElement("div");
    d.className = "air-m " + who; d.textContent = text;
    msgs.appendChild(d); msgs.scrollTop = msgs.scrollHeight;
    return d;
  }
  function toggle(force) {
    var open = force !== undefined ? force : !win.classList.contains("open");
    win.classList.toggle("open", open);
    btn.textContent = open ? "×" : "💬";
    if (open) { if (!msgs.children.length) add(GREETING, "bot"); setTimeout(function () { input.focus(); }, 50); }
  }
  btn.onclick = function () { toggle(); };
  win.querySelector(".air-x").onclick = function () { toggle(false); };

  form.onsubmit = function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text) return;
    add(text, "me"); input.value = ""; send.disabled = true;
    var typing = document.createElement("div");
    typing.className = "air-typing"; typing.textContent = "друкує…";
    msgs.appendChild(typing); msgs.scrollTop = msgs.scrollHeight;
    fetch(API + "/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: sid, niche: NICHE, business_name: BUSINESS || null })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.session_id) { sid = data.session_id; try { sessionStorage.setItem(SKEY, sid); } catch (e) {} }
        add(data.reply || "…", "bot");
      })
      .catch(function () { add("Немає зв'язку з сервером. Спробуйте ще раз.", "bot"); })
      .finally(function () { typing.remove(); send.disabled = false; input.focus(); });
  };

  window.AIReceptionist = { open: function () { toggle(true); }, close: function () { toggle(false); } };
  if (OPEN) toggle(true);
})();
