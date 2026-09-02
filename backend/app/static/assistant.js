/* The CabinetTron assistant — one widget, every app in the suite.
 *
 * Included by a single <script src="/assistant.js" defer> in each shell:
 * CabinetTron (React), Sterling, Optimus, Order Pack, Autobot. One file to
 * change, not five copies that drift.
 *
 * Everything lives in a shadow root so none of the five stylesheets can reach
 * in and none of these rules leak out — the apps have very different CSS and
 * a stray `button { }` rule would wreck this or vice versa.
 *
 * The launcher stays hidden until /assistant/status says the user may use it,
 * so nobody sees a button that will only refuse them.
 */
(function () {
  "use strict";
  if (window.__ctAssistant) return;           // survive a double include
  window.__ctAssistant = true;

  var API = "/api";
  var token = function () {
    try { return localStorage.getItem("cms_token"); } catch (e) { return null; }
  };
  var auth = function () {
    var t = token();
    return t ? { Authorization: "Bearer " + t } : {};
  };

  var CSS = [
    ":host{all:initial}",
    "*{box-sizing:border-box;font-family:'Segoe UI',system-ui,-apple-system,sans-serif}",
    ".launch{position:fixed;right:20px;bottom:20px;z-index:2147483000;width:52px;height:52px;",
    "border-radius:50%;border:none;cursor:pointer;background:#125952;color:#fff;font-size:22px;",
    "box-shadow:0 4px 16px rgba(0,0,0,.28);display:flex;align-items:center;justify-content:center}",
    ".launch:hover{background:#0d443e}",
    ".launch:focus-visible{outline:3px solid #2bb99f;outline-offset:2px}",
    ".panel{position:fixed;right:20px;bottom:84px;z-index:2147483000;width:412px;max-width:calc(100vw - 32px);",
    "height:min(620px,calc(100vh - 120px));background:#fff;border:1px solid #d7e0de;border-radius:12px;",
    "box-shadow:0 16px 48px rgba(0,0,0,.22);display:flex;flex-direction:column;overflow:hidden}",
    ".head{background:#125952;color:#fff;padding:11px 14px;display:flex;align-items:center;gap:8px;flex:0 0 auto}",
    ".head b{font-size:14px;font-weight:600}",
    ".head small{color:#a8ccc6;font-size:11.5px}",
    ".head .sp{margin-left:auto;display:flex;gap:4px}",
    ".head button{background:transparent;border:none;color:#cfe3df;cursor:pointer;font-size:16px;padding:2px 6px;border-radius:5px}",
    ".head button:hover{background:rgba(255,255,255,.16);color:#fff}",
    ".log{flex:1 1 auto;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:12px;background:#f7f9f8}",
    ".msg{font-size:13.5px;line-height:1.55;white-space:pre-wrap;word-wrap:break-word}",
    ".me{align-self:flex-end;max-width:85%;background:#125952;color:#fff;padding:8px 12px;border-radius:12px 12px 3px 12px}",
    ".ai{align-self:flex-start;max-width:100%;color:#1a2321}",
    ".tool{align-self:flex-start;font-size:11.5px;color:#5c6b67;font-style:italic}",
    ".err{align-self:flex-start;font-size:12.5px;color:#9e2b25;background:#fdeeee;padding:7px 10px;border-radius:7px;max-width:100%}",
    ".hint{color:#5c6b67;font-size:12.5px;line-height:1.6}",
    ".hint b{color:#1a2321;display:block;margin-bottom:5px;font-size:13px}",
    ".hint i{font-style:normal;display:block;margin:3px 0;cursor:pointer;color:#125952}",
    ".hint i:hover{text-decoration:underline}",
    ".foot{flex:0 0 auto;border-top:1px solid #e4ebe9;padding:9px;display:flex;gap:7px;background:#fff}",
    "textarea{flex:1;resize:none;border:1px solid #cbd6d3;border-radius:8px;padding:8px 10px;",
    "font-size:13.5px;line-height:1.4;max-height:110px;min-height:38px;font-family:inherit}",
    "textarea:focus{outline:none;border-color:#125952}",
    ".send{background:#125952;color:#fff;border:none;border-radius:8px;padding:0 15px;cursor:pointer;font-size:13.5px;font-weight:600}",
    ".send:disabled{background:#9db3af;cursor:default}",
    ".usage{padding:4px 14px 7px;font-size:11px;color:#8a9793;background:#f7f9f8;flex:0 0 auto}",
    "table{border-collapse:collapse;margin:7px 0;font-size:12.5px;width:100%}",
    "th,td{border:1px solid #dde5e3;padding:4px 7px;text-align:left}",
    "th{background:#eef3f2;font-weight:600}",
    "code{background:#eef3f2;padding:1px 4px;border-radius:3px;font-size:12px}",
    "@media (max-width:520px){.panel{right:8px;left:8px;width:auto;bottom:76px;height:calc(100vh - 96px)}}",
  ].join("");

  var host = document.createElement("div");
  document.body.appendChild(host);
  var root = host.attachShadow({ mode: "open" });
  var style = document.createElement("style");
  style.textContent = CSS;
  root.appendChild(style);

  var launch = document.createElement("button");
  launch.className = "launch";
  launch.title = "Ask the assistant";
  launch.setAttribute("aria-label", "Ask the assistant");
  launch.textContent = "✦";
  launch.style.display = "none";
  root.appendChild(launch);

  var panel = null;
  var history = [];
  var busy = false;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* Enough markdown for what the model actually sends back: tables, bold,
     code, headings. Not a full parser — escaping happens first, so nothing
     the model writes can inject markup. */
  function render(md) {
    var out = esc(md);
    var lines = out.split("\n");
    var html = [];
    var i = 0;
    while (i < lines.length) {
      if (/^\s*\|.*\|\s*$/.test(lines[i]) && i + 1 < lines.length
          && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
        var cells = function (row) {
          return row.trim().replace(/^\||\|$/g, "").split("|").map(function (c) { return c.trim(); });
        };
        var head = cells(lines[i]);
        i += 2;
        var body = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { body.push(cells(lines[i])); i++; }
        html.push("<table><thead><tr>" + head.map(function (h) { return "<th>" + h + "</th>"; }).join("")
          + "</tr></thead><tbody>" + body.map(function (r) {
            return "<tr>" + r.map(function (c) { return "<td>" + c + "</td>"; }).join("") + "</tr>";
          }).join("") + "</tbody></table>");
        continue;
      }
      html.push(lines[i]);
      i++;
    }
    return html.join("\n")
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/^### (.+)$/gm, "<b>$1</b>");
  }

  function pageContext() {
    var name = document.title || "CabinetTron";
    var path = location.pathname + (location.hash || "");
    return name + " (" + path + ")";
  }

  function build() {
    panel = document.createElement("div");
    panel.className = "panel";
    panel.innerHTML =
      '<div class="head"><b>Assistant</b><small>read-only</small>' +
      '<span class="sp"><button data-act="clear" title="New conversation">⟲</button>' +
      '<button data-act="close" title="Close">✕</button></span></div>' +
      '<div class="log"></div><div class="usage"></div>' +
      '<div class="foot"><textarea rows="1" placeholder="Ask about jobs, pricing, phases…"></textarea>' +
      '<button class="send">Ask</button></div>';
    root.appendChild(panel);

    var log = panel.querySelector(".log");
    var box = panel.querySelector("textarea");
    var send = panel.querySelector(".send");

    panel.querySelector('[data-act="close"]').onclick = toggle;
    panel.querySelector('[data-act="clear"]').onclick = function () {
      history = []; log.innerHTML = ""; panel.querySelector(".usage").textContent = ""; greet();
    };

    function add(cls, text) {
      var d = document.createElement("div");
      d.className = "msg " + cls;
      if (cls === "ai") d.innerHTML = render(text); else d.textContent = text;
      log.appendChild(d);
      log.scrollTop = log.scrollHeight;
      return d;
    }

    function greet() {
      var d = document.createElement("div");
      d.className = "hint";
      d.innerHTML = "<b>Ask me about your data.</b>" +
        "<i data-q=\"Which jobs are past their field measure date?\">Which jobs are past their field measure date?</i>" +
        "<i data-q=\"What is the margin on DRH1 Madison STD?\">What is the margin on DRH1 Madison STD?</i>" +
        "<i data-q=\"Show me every plan priced below 10% margin\">Show me every plan priced below 10% margin</i>" +
        "<i data-q=\"What is the price of B36 in each price group?\">What is the price of B36 in each price group?</i>";
      d.querySelectorAll("i").forEach(function (el) {
        el.onclick = function () { box.value = el.getAttribute("data-q"); ask(); };
      });
      log.appendChild(d);
    }

    function ask() {
      var text = box.value.trim();
      if (!text || busy) return;
      box.value = ""; box.style.height = "auto";
      add("me", text);
      history.push({ role: "user", content: text });
      busy = true; send.disabled = true; send.textContent = "…";

      var bubble = null, answer = "";
      fetch(API + "/assistant/ask", {
        method: "POST",
        headers: Object.assign({ "Content-Type": "application/json" }, auth()),
        body: JSON.stringify({ messages: history, page: pageContext() }),
      }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        var reader = r.body.getReader(), dec = new TextDecoder(), buf = "";
        (function pump() {
          return reader.read().then(function (res) {
            if (res.done) return finish();
            buf += dec.decode(res.value, { stream: true });
            var parts = buf.split("\n\n"); buf = parts.pop();
            parts.forEach(function (p) {
              if (p.indexOf("data: ") !== 0) return;
              var ev;
              try { ev = JSON.parse(p.slice(6)); } catch (e) { return; }
              if (ev.type === "text") {
                if (!bubble) bubble = add("ai", "");
                answer += ev.text;
                bubble.innerHTML = render(answer);
                log.scrollTop = log.scrollHeight;
              } else if (ev.type === "tool") {
                add("tool", "looking up " + ev.name.replace(/_/g, " ") + "…");
              } else if (ev.type === "usage") {
                panel.querySelector(".usage").textContent =
                  "~$" + ev.cost.toFixed(3) + " · " + ev.input + " in / " + ev.output + " out";
              } else if (ev.type === "error") {
                add("err", ev.message);
              }
            });
            return pump();
          });
        })();
      }).catch(function (e) {
        add("err", e.message === "HTTP 403" ? "The assistant is limited to admins."
          : e.message === "HTTP 503" ? "The assistant is not configured yet."
          : "Could not reach the assistant (" + e.message + ")");
        finish();
      });

      function finish() {
        if (answer) history.push({ role: "assistant", content: answer });
        busy = false; send.disabled = false; send.textContent = "Ask";
        box.focus();
      }
    }

    send.onclick = ask;
    box.addEventListener("input", function () {
      box.style.height = "auto";
      box.style.height = Math.min(box.scrollHeight, 110) + "px";
    });
    box.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); }
    });
    greet();
    setTimeout(function () { box.focus(); }, 40);
  }

  function toggle() {
    if (panel) { panel.remove(); panel = null; launch.textContent = "✦"; return; }
    build();
    launch.textContent = "✕";
  }
  launch.onclick = toggle;

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && panel) toggle();
  });

  // Only show the launcher to someone who can actually use it.
  fetch(API + "/assistant/status", { headers: auth() })
    .then(function (r) { return r.ok ? r.json() : { enabled: false }; })
    .then(function (s) { if (s.enabled) launch.style.display = "flex"; })
    .catch(function () { /* signed out or offline — stay hidden */ });
})();
