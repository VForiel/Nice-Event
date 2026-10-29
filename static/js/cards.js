// Cartes d'événements : « Ça m'intéresse » / « Pas pour moi » sans recharger la page, et « Afficher plus
// d'événements » qui ajoute la suite à la liste au lieu de recharger (on garde sa place dans le fil).
(function () {
  "use strict";

  document.addEventListener("submit", function (e) {
    var form = e.target.closest("form[data-interest]");
    if (!form || !window.fetch) return;
    e.preventDefault();
    var button = e.submitter || form.querySelector("button");
    var data = new FormData(form);
    data.set("value", button.value);
    fetch(form.action, { method: "POST", body: data, headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (answer) {
        form.querySelector(".ia-yes").setAttribute("aria-pressed", answer.value === 1 ? "true" : "false");
        form.querySelector(".ia-no").setAttribute("aria-pressed", answer.value === -1 ? "true" : "false");
        var card = form.closest(".card");
        if (card) card.classList.toggle("is-dismissed", answer.value === -1);
      })
      .catch(function () { form.submit(); });
  });

  document.addEventListener("click", function (e) {
    var link = e.target.closest("[data-results] .more a");
    if (!link || !window.fetch || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    var results = link.closest("[data-results]");
    link.setAttribute("aria-busy", "true");
    var url = new URL(link.href, location.href);
    var partial = new URL(url);
    partial.searchParams.set("partiel", "1");
    fetch(partial, { headers: { Accept: "text/html" }, credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        // La page suivante contient toute la liste jusque-là : le haut ne bouge pas, la suite s'ajoute en dessous.
        var y = window.scrollY;
        results.innerHTML = html;
        window.scrollTo(0, y);
        history.replaceState(history.state, "", url.pathname + url.search);
      })
      .catch(function () { location.href = link.href; });
  });
})();
