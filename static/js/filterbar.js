// Barre de filtres de l'agenda et de la carte : menus déroulants (un seul ouvert à la fois), calendrier de plage de
// dates, adresse avec rayon. Chaque changement met à jour l'adresse de la page et les résultats sans recharger
// (événement « filterbar:change », écouté ici pour la liste et par map.js pour la carte).
(function () {
  "use strict";

  var form = document.querySelector("[data-filterbar]");
  if (!form) return;
  var lang = document.documentElement.lang || "fr";
  var EMPTY = "_aucun"; // tout décoché : aucun résultat (plutôt que « tout »)

  form.querySelectorAll("[data-no-js]").forEach(function (el) { el.hidden = true; });

  // Menus déroulants -------------------------------------------------------------------------------------------
  var menus = Array.prototype.slice.call(form.querySelectorAll("details.dd"));
  menus.forEach(function (menu) {
    menu.addEventListener("toggle", function () {
      if (!menu.open) return;
      menus.forEach(function (other) { if (other !== menu) other.open = false; });
      var panel = menu.querySelector(".dd-panel");
      panel.classList.remove("dd-flip");
      var box = panel.getBoundingClientRect();
      if (box.right > window.innerWidth - 8) panel.classList.add("dd-flip");
    });
  });
  document.addEventListener("click", function (e) {
    menus.forEach(function (menu) { if (menu.open && !menu.contains(e.target)) menu.open = false; });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    menus.forEach(function (menu) {
      if (menu.open) { menu.open = false; menu.querySelector("summary").focus(); }
    });
  });

  function boxes(name) { return Array.prototype.slice.call(form.querySelectorAll("input[name='" + name + "']")); }

  form.addEventListener("click", function (e) {
    var all = e.target.closest("[data-check-all]");
    var none = e.target.closest("[data-check-none]");
    var only = e.target.closest("[data-check-only]");
    if (!all && !none && !only) return;
    e.preventDefault();
    var name = (all || none || only).dataset.checkAll || (all || none || only).dataset.checkNone || only.dataset.checkOnly;
    boxes(name).forEach(function (b) { b.checked = all ? true : only ? b.value === only.dataset.value : false; });
    changed();
  });

  // Résumé dans chaque bouton -----------------------------------------------------------------------------------
  function counts() {
    menus.forEach(function (menu) {
      var out = menu.querySelector("[data-dd-count]");
      var n = 0;
      var key = menu.dataset.dd;
      if (key === "types" || key === "sources" || key === "prix") {
        var list = menu.querySelectorAll("input[type=checkbox]");
        var checked = menu.querySelectorAll("input[type=checkbox]:checked").length;
        n = checked === list.length ? 0 : checked;
        if (checked === 0) n = "0";
      } else if (key === "dates") {
        var r = form.querySelector("input[name=quand]:checked");
        n = r && r.value ? 1 : 0;
      } else {
        n = menu.querySelectorAll("input[type=checkbox]:checked").length;
        menu.querySelectorAll("input[type=number][name], [data-near-value]").forEach(function (i) { if (i.value) n += 1; });
      }
      out.textContent = n ? String(n) : "";
      menu.classList.toggle("is-on", !!n);
    });
  }

  // Adresse de la page --------------------------------------------------------------------------------------------
  function query() {
    var params = new URLSearchParams();
    var groups = {};
    new FormData(form).forEach(function (value, name) {
      if (name === "csrfmiddlewaretoken" || value === "") return;
      (groups[name] = groups[name] || []).push(value);
    });
    ["categorie", "src", "prix"].forEach(function (name) {
      var total = boxes(name).length;
      var picked = groups[name] || [];
      if (picked.length === total) delete groups[name];
      else if (!picked.length) groups[name] = [EMPTY];
    });
    if ((groups.quand || [])[0] !== "dates") { delete groups.du; delete groups.au; }
    if (!groups.pres) delete groups.pres_label;
    Object.keys(groups).forEach(function (name) {
      groups[name].forEach(function (v) { params.append(name, v); });
    });
    return params.toString();
  }

  var timer = null;
  var last = query();
  function changed() {
    counts();
    clearTimeout(timer);
    timer = setTimeout(function () {
      var q = query();
      if (q === last) return;
      last = q;
      history.replaceState(null, "", location.pathname + (q ? "?" + q : ""));
      document.querySelectorAll("[data-keep-query]").forEach(function (a) {
        var url = new URL(a.href, location.href);
        url.search = q;
        a.href = url.toString();
      });
      var reset = form.querySelector("[data-reset]");
      if (reset) reset.hidden = !q && !form.querySelector("[data-custom-filter]");
      form.dispatchEvent(new CustomEvent("filterbar:change", { bubbles: true, detail: { query: q } }));
    }, 250);
  }
  form.addEventListener("change", function (e) {
    if (e.target.matches("[data-near-address], [data-near-km]")) return; // gérés plus bas
    if (e.target.name === "quand") {
      var cal = form.querySelector("[data-calendar]");
      cal.hidden = e.target.value !== "dates";
      if (e.target.value === "dates" && !form.querySelector("input[name=du]").value) return; // attendre les dates
    }
    changed();
  });
  form.addEventListener("input", function (e) {
    if (e.target.type === "number" && e.target.name) changed();
  });
  form.addEventListener("submit", function (e) {
    if (e.submitter && e.submitter.getAttribute("formaction")) return; // « Retirer » le filtre personnalisé
    e.preventDefault();
    menus.forEach(function (menu) { menu.open = false; });
    changed();
  });
  var search = form.querySelector("input[name=q]");
  if (search) search.addEventListener("search", changed);

  // Liste : remplacer les résultats en place ---------------------------------------------------------------------
  var results = document.querySelector("[data-results]");
  if (results) {
    var pending = null;
    form.addEventListener("filterbar:change", function (e) {
      if (pending) pending.abort();
      pending = new AbortController();
      results.classList.add("is-loading");
      fetch(form.action + "?" + e.detail.query + (e.detail.query ? "&" : "") + "partiel=1",
        { signal: pending.signal, headers: { Accept: "text/html" } })
        .then(function (r) { return r.text(); })
        .then(function (html) { results.innerHTML = html; results.classList.remove("is-loading"); })
        .catch(function () { /* requête remplacée par une plus récente */ });
    });
  }

  // Calendrier de plage de dates ---------------------------------------------------------------------------------
  var cal = form.querySelector("[data-calendar]");
  if (cal) {
    var from = form.querySelector("input[name=du]");
    var to = form.querySelector("input[name=au]");
    var today = cal.dataset.today;
    var shown = (from.value || today).slice(0, 7) + "-01";
    var grid = document.createElement("div");
    grid.className = "cal";
    cal.insertBefore(grid, cal.querySelector("[data-calendar-hint]"));

    var iso = function (d) { return d.toISOString().slice(0, 10); };
    var parse = function (s) { return new Date(s + "T12:00:00Z"); };
    var monthName = new Intl.DateTimeFormat(lang, { month: "long", year: "numeric", timeZone: "UTC" });
    var shortDate = new Intl.DateTimeFormat(lang, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
    var hint = cal.querySelector("[data-calendar-hint]");
    var hintText = hint.textContent;
    var describe = function () {
      if (!from.value) { hint.textContent = hintText; return; }
      hint.textContent = shortDate.format(parse(from.value)) + (to.value && to.value !== from.value ? " → " + shortDate.format(parse(to.value)) : "");
    };
    var dayName = new Intl.DateTimeFormat(lang, { weekday: "narrow", timeZone: "UTC" });

    var draw = function () {
      grid.innerHTML = "";
      var first = parse(shown);
      var head = document.createElement("div");
      head.className = "cal-head";
      var prev = document.createElement("button");
      prev.type = "button"; prev.className = "cal-nav"; prev.textContent = "‹"; prev.setAttribute("aria-label", "‹");
      prev.disabled = shown <= today.slice(0, 7) + "-01";
      var next = document.createElement("button");
      next.type = "button"; next.className = "cal-nav"; next.textContent = "›"; next.setAttribute("aria-label", "›");
      var title = document.createElement("span");
      title.textContent = monthName.format(first);
      prev.addEventListener("click", function (e) { e.stopPropagation(); move(-1); });
      next.addEventListener("click", function (e) { e.stopPropagation(); move(1); });
      head.appendChild(prev); head.appendChild(title); head.appendChild(next);
      grid.appendChild(head);
      var days = document.createElement("div");
      days.className = "cal-days";
      for (var w = 0; w < 7; w++) {
        var label = document.createElement("span");
        label.className = "cal-dow";
        label.textContent = dayName.format(new Date(Date.UTC(2024, 0, 1 + w))); // 1er janvier 2024 : un lundi
        days.appendChild(label);
      }
      var offset = (first.getUTCDay() + 6) % 7;
      for (var i = 0; i < offset; i++) days.appendChild(document.createElement("span"));
      var d = new Date(first);
      while (d.getUTCMonth() === first.getUTCMonth()) {
        var value = iso(d);
        var b = document.createElement("button");
        b.type = "button";
        b.className = "cal-day";
        b.textContent = String(d.getUTCDate());
        b.dataset.day = value;
        b.disabled = value < today;
        if (from.value && value === from.value) b.classList.add("is-start");
        if (to.value && value === to.value) b.classList.add("is-end");
        if (from.value && to.value && value > from.value && value < to.value) b.classList.add("is-in");
        if (value === today) b.classList.add("is-today");
        days.appendChild(b);
        d.setUTCDate(d.getUTCDate() + 1);
      }
      grid.appendChild(days);
      describe();
    };
    var move = function (step) {
      var d = parse(shown);
      d.setUTCMonth(d.getUTCMonth() + step);
      shown = iso(d).slice(0, 7) + "-01";
      draw();
    };
    grid.addEventListener("click", function (e) {
      var b = e.target.closest(".cal-day");
      if (!b) return;
      e.stopPropagation();
      var value = b.dataset.day;
      if (!from.value || to.value || value < from.value) {
        from.value = value; to.value = "";
      } else {
        to.value = value;
      }
      form.querySelector("input[name=quand][value=dates]").checked = true;
      draw();
      changed();
    });
    draw();
  }

  // Près d'une adresse --------------------------------------------------------------------------------------------
  var near = form.querySelector("[data-near]");
  if (near) {
    var hidden = near.querySelector("[data-near-value]");
    var address = near.querySelector("[data-near-address]");
    var list = near.querySelector("[data-near-list]");
    var km = near.querySelector("[data-near-km]");
    var clear = near.querySelector("[data-near-clear]");
    var point = hidden.value ? hidden.value.split(",").slice(0, 2) : null;

    var set = function (lat, lon, label) {
      point = lat == null ? null : [Math.round(lat * 1e5) / 1e5, Math.round(lon * 1e5) / 1e5];
      hidden.value = point ? point[0] + "," + point[1] + "," + (km.value || 5) : "";
      if (label != null) address.value = label;
      clear.hidden = !point;
      changed();
    };
    var closeList = function () { list.hidden = true; list.innerHTML = ""; };
    var wait = null;
    address.addEventListener("input", function () {
      clearTimeout(wait);
      var q = address.value.trim();
      if (q.length < 3) { closeList(); return; }
      wait = setTimeout(function () {
        fetch(form.dataset.geocode + "?q=" + encodeURIComponent(q), { headers: { Accept: "application/json" } })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            list.innerHTML = "";
            (data.results || []).forEach(function (r) {
              var li = document.createElement("li");
              li.setAttribute("role", "option");
              li.textContent = r.label;
              li.addEventListener("mousedown", function (ev) { ev.preventDefault(); closeList(); set(r.lat, r.lon, r.label); });
              list.appendChild(li);
            });
            list.hidden = !list.children.length;
          })
          .catch(closeList);
      }, 250);
    });
    address.addEventListener("blur", function () { setTimeout(closeList, 150); });
    address.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); var first = list.querySelector("li"); if (first) first.dispatchEvent(new MouseEvent("mousedown")); }
    });
    km.addEventListener("input", function () { if (point) set(point[0], point[1]); });
    clear.addEventListener("click", function () { address.value = ""; set(null); });
    var here = near.querySelector("[data-near-here]");
    if (navigator.geolocation) {
      here.addEventListener("click", function () {
        navigator.geolocation.getCurrentPosition(function (pos) {
          set(pos.coords.latitude, pos.coords.longitude, here.textContent.trim());
        });
      });
    } else {
      here.hidden = true;
    }
  }

  counts();
})();
