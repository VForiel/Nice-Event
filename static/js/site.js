// Menu mobile, bascule de thème, copie de lien, bandeau d'annonce.
(function () {
  "use strict";

  var root = document.documentElement;

  function systemDark() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  // Le menu mobile commence juste sous l'en-tête, quelle que soit la hauteur des bandeaux au-dessus.
  function placeMenu() {
    var header = document.querySelector(".site-header");
    if (header) root.style.setProperty("--nav-top", Math.max(0, header.getBoundingClientRect().bottom) + "px");
  }
  window.addEventListener("resize", placeMenu);

  document.addEventListener("click", function (e) {
    var toggle = e.target.closest(".nav-toggle");
    if (toggle) {
      var nav = document.getElementById(toggle.getAttribute("aria-controls"));
      var open = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", String(open));
      if (open) placeMenu();
      nav.classList.toggle("is-open", open);
      root.classList.toggle("menu-open", open);
      return;
    }

    if (e.target.closest(".theme-toggle")) {
      var current = root.dataset.theme || (systemDark() ? "dark" : "light");
      var next = current === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try { localStorage.setItem("theme", next); } catch (err) { /* stockage indisponible */ }
      return;
    }

    // Actions irréversibles : demander confirmation avant d'envoyer le formulaire
    var risky = e.target.closest("[data-confirm]");
    if (risky && !window.confirm(risky.dataset.confirm)) {
      e.preventDefault();
      return;
    }

    var copy = e.target.closest("[data-copy]");
    if (copy && navigator.clipboard) {
      navigator.clipboard.writeText(copy.dataset.copy).then(function () {
        var label = copy.querySelector("[data-copy-label]");
        if (!label) return;
        var before = label.textContent;
        label.textContent = copy.dataset.copied || "OK";
        setTimeout(function () { label.textContent = before; }, 2000);
      });
    }
  });

  // Bandeau d'annonce : refermé une fois, il ne revient pas (jusqu'à la prochaine annonce)
  var banner = document.querySelector("[data-announce]");
  if (banner) {
    var key = "announce-" + banner.dataset.announce;
    try { if (localStorage.getItem(key)) banner.classList.add("is-dismissed"); } catch (e) { /* rien */ }
    banner.addEventListener("click", function (e) {
      if (!e.target.closest("[data-announce-close]")) return;
      banner.classList.add("is-dismissed");
      try { localStorage.setItem(key, "1"); } catch (err) { /* rien */ }
    });
  }

  // Formulaire refusé : amener le résumé des erreurs sous les yeux (sinon on croit que c'est enregistré)
  var formError = document.querySelector("[data-form-error]");
  if (formError) {
    formError.scrollIntoView({ block: "center" });
    formError.focus({ preventScroll: true });
  }

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    var toggle = document.querySelector(".nav-toggle[aria-expanded='true']");
    if (toggle) toggle.click();
  });
})();

// Partage natif (mobile) : le bouton n'apparaît que si le navigateur sait partager.
(function () {
  "use strict";
  document.querySelectorAll("[data-share]").forEach(function (btn) {
    if (!navigator.share) return;
    btn.hidden = false;
    btn.addEventListener("click", function () {
      navigator.share({ title: btn.dataset.shareTitle, text: btn.dataset.shareTitle, url: btn.dataset.shareUrl })
        .catch(function () { /* partage annulé */ });
    });
  });
})();

// Vidéos YouTube, Vimeo, Dailymotion : le lecteur n'est chargé qu'au clic (rien n'est demandé à ces sites avant).
(function () {
  "use strict";
  document.addEventListener("click", function (e) {
    var button = e.target.closest(".embed-play");
    if (!button) return;
    var box = button.closest("[data-embed]");
    var frame = document.createElement("iframe");
    var src = box.dataset.embed;
    frame.src = src + (src.indexOf("?") < 0 ? "?" : "&") + "autoplay=1";
    frame.title = box.dataset.embedTitle || "";
    frame.allow = "autoplay; fullscreen; picture-in-picture; encrypted-media";
    frame.allowFullscreen = true;
    frame.referrerPolicy = "strict-origin-when-cross-origin";
    box.replaceChildren(frame);
    box.classList.add("is-playing");
  });
})();

// Fenêtres ouvertes à l'arrivée sur la page (soutien au site après la création d'un événement).
(function () {
  "use strict";
  document.querySelectorAll("dialog[data-open-on-load]").forEach(function (dialog) {
    if (typeof dialog.showModal !== "function") return;
    dialog.showModal();
    dialog.addEventListener("click", function (e) {
      if (e.target === dialog) dialog.close();  // clic sur le fond
    });
  });
})();
