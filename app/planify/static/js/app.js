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
});
