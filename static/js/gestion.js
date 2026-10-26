// Gestion : compteurs de caractères des textes de diffusion (X compte chaque lien pour 23 caractères).
(function () {
  "use strict";
  var URL_RE = /https?:\/\/\S+/g;

  document.querySelectorAll("[data-count-for]").forEach(function (counter) {
    var area = document.getElementById(counter.dataset.countFor);
    if (!area) return;
    var limit = parseInt(area.dataset.limit, 10);
    var network = area.dataset.network;
    function count() {
      var text = area.value;
      if (network === "x") text = text.replace(URL_RE, "xxxxxxxxxxxxxxxxxxxxxxx");
      var n = Array.from(text).length;
      counter.textContent = n;
      counter.classList.toggle("warn", n > limit);
    }
    area.addEventListener("input", count);
    count();
  });
})();
