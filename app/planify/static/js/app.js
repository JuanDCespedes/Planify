document.addEventListener("DOMContentLoaded", () => {
  const themeToggle = document.querySelector("[data-theme-toggle]");
  const themeLabel = document.querySelector("#theme-label");

  const syncThemeControl = () => {
    const isDark = document.documentElement.dataset.theme === "dark";
    if (themeToggle) themeToggle.checked = isDark;
    if (themeLabel) themeLabel.textContent = isDark ? "Modo oscuro" : "Modo claro";
  };

  syncThemeControl();
  themeToggle?.addEventListener("change", () => {
    const theme = themeToggle.checked ? "dark" : "light";
    document.documentElement.dataset.theme = theme;
    syncThemeControl();
    try {
      localStorage.setItem("planify-theme", theme);
    } catch (error) {
      console.warn("No se pudo guardar la preferencia de tema.", error);
    }
  });

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  const menuToggle = document.querySelector("[data-menu-toggle]");
  menuToggle?.addEventListener("click", () => {
    const isOpen = document.body.classList.toggle("menu-open");
    menuToggle.setAttribute("aria-expanded", String(isOpen));
  });

  const pushStatus = document.querySelector("[data-push-status]");
  const browserStatus = document.querySelector("[data-browser-notification-status]");
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
  const registerServiceWorker = async () => {
    if (!("serviceWorker" in navigator)) throw new Error("Este navegador no admite notificaciones en segundo plano.");
    return navigator.serviceWorker.register("/service-worker.js");
  };
  const showStatus = (element, message) => {
    if (element) element.textContent = message;
  };
  const base64UrlToBytes = (value) => {
    const padding = "=".repeat((4 - (value.length % 4)) % 4);
    const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
    return Uint8Array.from(window.atob(base64), (character) => character.charCodeAt(0));
  };

  document.querySelector("[data-enable-browser-notifications]")?.addEventListener("click", async () => {
    if (!("Notification" in window)) {
      showStatus(browserStatus, "Este navegador no admite notificaciones del sistema.");
      return;
    }
    const permission = await Notification.requestPermission();
    showStatus(
      browserStatus,
      permission === "granted"
        ? "Avisos del navegador permitidos. Mantén Planify abierto para recibirlos."
        : "No se concedió el permiso. Puedes cambiarlo desde los ajustes del navegador.",
    );
  });

  document.querySelector("[data-enable-push]")?.addEventListener("click", async () => {
    try {
      if (!("PushManager" in window) || !("Notification" in window)) {
        throw new Error("Este navegador no admite notificaciones push.");
      }
      if (Notification.permission !== "granted") {
        const permission = await Notification.requestPermission();
        if (permission !== "granted") throw new Error("No se concedió el permiso para mostrar notificaciones.");
      }
      const registration = await registerServiceWorker();
      const keyResponse = await fetch("/api/notifications/push-key");
      if (!keyResponse.ok) throw new Error("El servidor no tiene configuradas las claves push.");
      const { public_key: publicKey } = await keyResponse.json();
      let subscription = await registration.pushManager.getSubscription();
      if (!subscription) {
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: base64UrlToBytes(publicKey),
        });
      }
      const response = await fetch("/api/notifications/push-subscription", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({ subscription: subscription.toJSON() }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "No se pudo guardar la suscripción.");
      showStatus(pushStatus, "Notificaciones push activadas en este navegador.");
    } catch (error) {
      showStatus(pushStatus, error.message || "No se pudo activar el envío push.");
    }
  });

  const playRoutineSound = () => {
    try {
      const audio = new AudioContext();
      const oscillator = audio.createOscillator();
      const gain = audio.createGain();
      oscillator.frequency.value = 660;
      gain.gain.setValueAtTime(0.08, audio.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + 0.25);
      oscillator.connect(gain);
      gain.connect(audio.destination);
      oscillator.start();
      oscillator.stop(audio.currentTime + 0.25);
      oscillator.onended = () => audio.close();
    } catch (error) {
      console.warn("El navegador no pudo reproducir el sonido de la notificación.", error);
    }
  };

  const pollNotifications = async () => {
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    let lastId;
    try {
      lastId = localStorage.getItem("planify-last-notification-id");
    } catch (error) {
      console.warn("No se pudo leer el último aviso guardado.", error);
      return;
    }
    const url = lastId === null
      ? "/api/notifications"
      : `/api/notifications?after=${encodeURIComponent(lastId)}`;
    try {
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`La consulta de notificaciones respondió ${response.status}.`);
      const data = await response.json();
      if (lastId === null) {
        localStorage.setItem("planify-last-notification-id", String(data.latest_id));
        return;
      }
      for (const item of data.notifications) {
        const registration = await registerServiceWorker();
        await registration.showNotification(item.title, {
          body: item.message,
          tag: `planify-${item.id}`,
          data: { url: "/notifications" },
        });
        if (item.sound_enabled) playRoutineSound();
        lastId = String(item.id);
      }
      localStorage.setItem("planify-last-notification-id", lastId);
    } catch (error) {
      console.error("No se pudieron consultar las notificaciones.", error);
    }
  };

  if ("serviceWorker" in navigator) {
    registerServiceWorker().catch((error) => {
      console.warn("No se pudo registrar el service worker de Planify.", error);
    });
  }
  pollNotifications();
  window.setInterval(pollNotifications, 30000);
});
