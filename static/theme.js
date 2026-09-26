/* Aplica o tema antes da primeira pintura, para não piscar.
   Fica em arquivo próprio (e não inline no HTML) porque a CSP do servidor é
   `script-src 'self'` — sem hash nem nonce, um <script> inline seria bloqueado. */
(function () {
  var root = document.documentElement;
  try {
    var stored = localStorage.getItem("alldown.theme");
    var theme =
      stored === "light" || stored === "dark"
        ? stored
        : window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches
          ? "light"
          : "dark";
    root.dataset.colorScheme = theme;
  } catch (error) {
    root.dataset.colorScheme = "dark";
  }
})();
