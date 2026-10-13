// "Install app": Chromium browsers fire beforeinstallprompt, which we hold on to and trigger from our own button.
// Safari on iPhone/iPad never fires it, so we show a short "Share -> Add to Home Screen" tip instead.
import { getItem, setItem } from "./storage.js";

export const IOS_HINT_KEY = "safecross.iosHintDismissed.v1";

export const isStandalone = () =>
  Boolean((window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) || window.navigator.standalone === true);

export const isIos = () => {
  const ua = navigator.userAgent || "";
  const iPadOs = navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1; // iPadOS 13+ reports as a Mac
  return /iphone|ipad|ipod/i.test(ua) || iPadOs;
};

export function initInstall({ button, iosHint, iosDismiss }) {
  let deferredPrompt = null;

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault(); // stop the browser's own mini-infobar; we show our button
    deferredPrompt = event;
    if (!isStandalone()) button.hidden = false;
  });

  button.addEventListener("click", async () => {
    if (!deferredPrompt) return;
    const promptEvent = deferredPrompt;
    deferredPrompt = null; // a prompt can only be used once
    button.hidden = true;
    promptEvent.prompt();
    try { await promptEvent.userChoice; } catch { /* the user closed it */ }
  });

  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    button.hidden = true;
    iosHint.hidden = true;
  });

  if (isIos() && !isStandalone() && getItem(IOS_HINT_KEY) !== "1") iosHint.hidden = false;
  iosDismiss.addEventListener("click", () => {
    setItem(IOS_HINT_KEY, "1");
    iosHint.hidden = true;
  });
}
