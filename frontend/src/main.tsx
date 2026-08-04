import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

// PWA auto-update: the service worker uses skipWaiting + clientsClaim, but the
// already-open page won't run the new build until it reloads. Reload once when a
// freshly-deployed worker takes control, and proactively check for updates on
// load and whenever the app regains focus — otherwise a cached build sticks
// around and new changes never appear.
if ("serviceWorker" in navigator) {
  const hadController = !!navigator.serviceWorker.controller;
  let reloading = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!hadController || reloading) return; // skip the very first install claim
    reloading = true;
    window.location.reload();
  });
  navigator.serviceWorker.ready.then((reg) => {
    reg.update();
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") reg.update();
    });
    setInterval(() => reg.update(), 30 * 60 * 1000);
  });
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
