/**
 * AI Receptionist embed script.
 *
 * A client puts one line on their site:
 *   <script src="https://YOUR-APP.vercel.app/embed.js" defer></script>
 *
 * It draws the chat bubble on their page and loads the chat itself in an
 * iframe, so their CSS can't break the widget and the widget can't break
 * their site.
 *
 * Optional attributes on the script tag:
 *   data-color="#1f6feb"   bubble colour
 *   data-position="left"   corner to dock into (default: right)
 */
(function () {
  "use strict";

  if (window.__aiReceptionistLoaded) return;
  window.__aiReceptionistLoaded = true;

  // currentScript is set for a normal <script src>, but not when the tag is
  // injected by a framework loader — fall back to finding our own tag.
  var script =
    document.currentScript ||
    document.querySelector('script[src*="embed.js"]');
  var origin = new URL(script.src, location.href).origin;
  var color = script.getAttribute("data-color") || "#1f6feb";
  var side = script.getAttribute("data-position") === "left" ? "left" : "right";

  var BUBBLE_SIZE = 56;
  var open = false;
  var loaded = false;

  var root = document.createElement("div");
  root.style.cssText =
    "position:fixed;bottom:20px;" + side + ":20px;z-index:2147483000;" +
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;";

  var panel = document.createElement("div");
  panel.style.cssText =
    "position:absolute;bottom:" + (BUBBLE_SIZE + 14) + "px;" + side + ":0;" +
    "width:380px;height:min(600px,calc(100vh - 120px));" +
    "opacity:0;transform:translateY(12px) scale(0.98);pointer-events:none;" +
    "transition:opacity .18s ease,transform .18s ease;";

  var frame = document.createElement("iframe");
  frame.title = "Chat with our receptionist";
  frame.style.cssText =
    "width:100%;height:100%;border:0;border-radius:16px;background:transparent;" +
    "box-shadow:0 12px 48px rgba(15,23,42,.24);";

  var button = document.createElement("button");
  button.type = "button";
  button.setAttribute("aria-label", "Open chat");
  button.style.cssText =
    "width:" + BUBBLE_SIZE + "px;height:" + BUBBLE_SIZE + "px;border:0;border-radius:50%;" +
    "background:" + color + ";color:#fff;cursor:pointer;display:flex;align-items:center;" +
    "justify-content:center;box-shadow:0 6px 20px rgba(15,23,42,.28);transition:transform .15s ease;";

  var ICON_CHAT =
    '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9.6 9.6 0 0 1-2.9-.4L4 21l1.4-4a8.2 8.2 0 0 1-1.4-4.6 8.4 8.4 0 0 1 9-8.4 8.4 8.4 0 0 1 8 7.5z" ' +
    'stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>';
  var ICON_CLOSE =
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';

  button.innerHTML = ICON_CHAT;
  button.addEventListener("mouseenter", function () {
    button.style.transform = "scale(1.06)";
  });
  button.addEventListener("mouseleave", function () {
    button.style.transform = "scale(1)";
  });

  function fitToScreen() {
    if (window.innerWidth > 480) return;
    // On a phone the panel takes the whole screen instead of floating.
    panel.style.cssText +=
      ";position:fixed;inset:0;width:100vw;height:100dvh;bottom:0;right:0;left:0;";
    frame.style.borderRadius = "0";
  }

  function setOpen(next) {
    open = next;
    if (open && !loaded) {
      // Deferred until first open so the widget costs nothing on page load.
      frame.src = origin + "/widget";
      loaded = true;
    }
    panel.style.opacity = open ? "1" : "0";
    panel.style.transform = open ? "translateY(0) scale(1)" : "translateY(12px) scale(0.98)";
    panel.style.pointerEvents = open ? "auto" : "none";
    button.innerHTML = open ? ICON_CLOSE : ICON_CHAT;
    button.setAttribute("aria-label", open ? "Close chat" : "Open chat");
    if (open) fitToScreen();
  }

  button.addEventListener("click", function () {
    setOpen(!open);
  });

  // A message asked for before the chat finished loading waits here.
  var pending = null;
  var ready = false;

  function flush() {
    if (!ready || !pending) return;
    frame.contentWindow.postMessage({ type: "ai-receptionist:prefill", text: pending }, origin);
    pending = null;
  }

  /**
   * What the host page can call:
   *   aiReceptionist.open()               open the chat
   *   aiReceptionist.open("I want a...")  open it and send that message
   *   aiReceptionist.close()
   *
   * Or, with no JavaScript at all, put data-ai-receptionist on any element:
   *   <button data-ai-receptionist>Talk to us</button>
   *   <a data-ai-receptionist data-ai-receptionist-message="Tell me about 1041 Barton Springs">…</a>
   */
  window.aiReceptionist = {
    open: function (message) {
      if (message) {
        pending = String(message);
        ready = false;
      }
      setOpen(true);
      flush();
    },
    close: function () {
      setOpen(false);
    },
    toggle: function () {
      setOpen(!open);
    },
  };

  // Delegated, so it also picks up elements added to the page later.
  document.addEventListener("click", function (event) {
    var trigger = event.target.closest && event.target.closest("[data-ai-receptionist]");
    if (!trigger) return;
    event.preventDefault();
    window.aiReceptionist.open(trigger.getAttribute("data-ai-receptionist-message"));
  });

  window.addEventListener("message", function (event) {
    if (event.origin !== origin || !event.data) return;
    if (event.data.type === "ai-receptionist:close") setOpen(false);
    if (event.data.type === "ai-receptionist:ready") {
      ready = true;
      flush();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && open) setOpen(false);
  });

  panel.appendChild(frame);
  root.appendChild(panel);
  root.appendChild(button);

  function mount() {
    document.body.appendChild(root);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();
