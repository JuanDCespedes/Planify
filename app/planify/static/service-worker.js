self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (error) {
    payload = { title: "Planify", body: event.data?.text() || "Tienes un nuevo recordatorio." };
  }
  event.waitUntil(
    self.registration.showNotification(payload.title || "Planify", {
      body: payload.body || "Tienes un nuevo recordatorio.",
      tag: payload.tag || "planify-notification",
      data: { url: payload.url || "/notifications" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "/notifications", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      const existing = clients.find((client) => client.url === target);
      if (existing) return existing.focus();
      return self.clients.openWindow(target);
    }),
  );
});
