// Formulaire de publication : trois catégories au plus, compteur du résumé, champs qui dépendent d'un choix,
// suggestions de lieux déjà connus et d'adresses (BAN, interrogée par le serveur : /api/adresses/).
(function () {
  "use strict";

  var form = document.querySelector(".event-form");
  if (!form) return;

  // Catégories : au plus data-max cases cochées
  var picker = form.querySelector(".cat-picker");
  if (picker) {
    var max = parseInt(picker.dataset.max, 10) || 3;
    var update = function () {
      var boxes = picker.querySelectorAll("input[type=checkbox]");
      var checked = picker.querySelectorAll("input:checked").length;
      boxes.forEach(function (b) { b.disabled = !b.checked && checked >= max; });
    };
    picker.addEventListener("change", update);
    update();
  }

  // Compteur de caractères
  form.querySelectorAll("[data-counter]").forEach(function (counter) {
    var input = document.getElementById(counter.dataset.counter);
    var max = parseInt(counter.dataset.max, 10);
    var show = function () { counter.textContent = input.value.length + " / " + max; };
    input.addEventListener("input", show);
    show();
  });

  // Champs conditionnels
  function radioValue(name) {
    var checked = form.querySelector("input[name='" + name + "']:checked");
    return checked ? checked.value : "";
  }
  function refresh() {
    form.querySelectorAll("[data-hide-if]").forEach(function (el) {
      var box = document.getElementById(el.dataset.hideIf);
      el.hidden = !!(box && box.checked);
    });
    form.querySelectorAll("[data-show-if]").forEach(function (el) {
      var box = document.getElementById(el.dataset.showIf);
      el.hidden = !(box && box.checked);
    });
    form.querySelectorAll("[data-show-if-value]").forEach(function (el) {
      var parts = el.dataset.showIfValue.split(":");
      el.hidden = parts[1].split(",").indexOf(radioValue(parts[0])) === -1;
    });
  }
  form.addEventListener("change", refresh);
  refresh();

  // Suggestions ------------------------------------------------------------------------------------------------
  var venueInput = form.querySelector("[data-venue-search]");
  var addressInput = form.querySelector("[data-address-search]");
  var commune = form.querySelector("select[name=commune]");
  var venueId = form.querySelector("input[name=venue_id]");
  var lat = form.querySelector("input[name=lat]");
  var lon = form.querySelector("input[name=lon]");
  var located = form.querySelector("[data-located]");

  function setPosition(a, b) {
    lat.value = a == null ? "" : a;
    lon.value = b == null ? "" : b;
    if (located) located.hidden = a == null;
  }

  function suggest(input, list, url, render, pick) {
    var timer = null, items = [], active = -1;
    function close() { list.hidden = true; list.innerHTML = ""; items = []; active = -1; }
    function show(results) {
      list.innerHTML = "";
      items = results;
      results.forEach(function (r, i) {
        var li = document.createElement("li");
        li.setAttribute("role", "option");
        render(li, r);
        li.addEventListener("mousedown", function (e) { e.preventDefault(); pick(r); close(); });
        list.appendChild(li);
      });
      list.hidden = !results.length;
    }
    input.setAttribute("aria-autocomplete", "list");
    input.addEventListener("input", function () {
      clearTimeout(timer);
      var q = input.value.trim();
      if (q.length < 3) { close(); return; }
      timer = setTimeout(function () {
        fetch(url(q), { headers: { Accept: "application/json" } })
          .then(function (r) { return r.ok ? r.json() : { results: [] }; })
          .then(function (data) { if (input.value.trim() === q) show(data.results || []); })
          .catch(close);
      }, 250);
    });
    input.addEventListener("keydown", function (e) {
      if (list.hidden) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        list.querySelectorAll("li").forEach(function (li, i) { li.classList.toggle("is-active", i === active); });
      } else if (e.key === "Enter" && active >= 0) {
        e.preventDefault(); pick(items[active]); close();
      } else if (e.key === "Escape") { close(); }
    });
    input.addEventListener("blur", function () { setTimeout(close, 150); });
  }

  if (venueInput) {
    var venueList = form.querySelector(".suggestions[data-for=venue]");
    suggest(venueInput, venueList,
      function (q) { return form.dataset.venues + "?q=" + encodeURIComponent(q); },
      function (li, r) {
        var b = document.createElement("b"); b.textContent = r.name; li.appendChild(b);
        var s = document.createElement("span"); s.textContent = [r.address, r.commune_name].filter(Boolean).join(", ");
        li.appendChild(s);
      },
      function (r) {
        venueInput.value = r.name;
        venueId.value = r.id;
        if (addressInput) addressInput.value = r.address;
        if (commune) commune.value = r.commune;
        setPosition(r.lat, r.lon);
      });
    venueInput.addEventListener("input", function () { venueId.value = ""; });
  }

  if (addressInput) {
    var addressList = form.querySelector(".suggestions[data-for=address]");
    suggest(addressInput, addressList,
      function (q) { return form.dataset.addresses + "?q=" + encodeURIComponent(q) + (commune && commune.value ? "&commune=" + commune.value : ""); },
      function (li, r) { li.textContent = r.label; },
      function (r) {
        addressInput.value = r.name;
        if (commune && r.commune) commune.value = r.commune;
        venueId.value = "";
        setPosition(r.lat, r.lon);
      });
    addressInput.addEventListener("input", function () { setPosition(null, null); venueId.value = ""; });
    if (commune) commune.addEventListener("change", function () { setPosition(null, null); });
  }
  if (lat && lat.value && located) located.hidden = false;
})();
