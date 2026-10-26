// Carte des événements : Leaflet, fond de carte servi par le site (PMTiles, protomaps-leaflet), marqueurs emoji
// regroupés, aperçu au clic. Aucune requête vers un service tiers.
(function () {
  "use strict";

  var el = document.getElementById("map");
  if (!el || !window.L) return;
  var d = el.dataset;
  var status = document.querySelector("[data-map-status]");

  function dark() {
    var t = document.documentElement.dataset.theme;
    if (t) return t === "dark";
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  var region = L.latLngBounds([43.40, 6.55], [44.42, 7.80]);
  var map = L.map(el, { maxBounds: region.pad(0.2), minZoom: 8, maxZoom: 18, zoomControl: true, attributionControl: true })
    .setView([43.705, 7.262], 12);
  map.attributionControl.setPrefix(false);

  var base = null;
  function setBase() {
    if (!window.protomapsL) return;
    if (base) map.removeLayer(base);
    base = protomapsL.leafletLayer({ url: d.tiles, flavor: dark() ? "dark" : "light", lang: d.lang || "fr",
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Protomaps' });
    base.addTo(map);
  }
  setBase();
  document.addEventListener("click", function (e) {
    if (e.target.closest(".theme-toggle")) setTimeout(setBase, 0);
  });

  var cluster = L.markerClusterGroup({
    showCoverageOnHover: false, maxClusterRadius: 44, spiderfyOnMaxZoom: true,
    iconCreateFunction: function (c) {
      return L.divIcon({ html: "<span>" + c.getChildCount() + "</span>", className: "cluster", iconSize: [44, 44] });
    }
  });
  map.addLayer(cluster);

  function text(tag, cls, value) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (value) node.textContent = value;
    return node;
  }

  function preview(ev) {
    var box = text("div", "popup");
    if (ev.photo) {
      var img = document.createElement("img");
      img.src = ev.photo; img.alt = ""; img.loading = "lazy";
      box.appendChild(img);
    } else {
      box.appendChild(text("div", "popup-art tone-" + ev.tone, ev.emoji));
    }
    var body = text("div", "popup-body");
    var tags = text("div", "tags");
    if (ev.cancelled) tags.appendChild(text("span", "tag tag-state state-cancelled", d.labelCancelled));
    tags.appendChild(text("span", "tag tag-cat tone-" + ev.tone, ev.category));
    tags.appendChild(text("span", ev.free ? "tag tag-free" : "tag tag-price", ev.price));
    if (ev.en) { var en = text("span", "tag tag-en", "EN friendly"); en.lang = "en"; tags.appendChild(en); }
    body.appendChild(tags);
    body.appendChild(text("h3", "popup-title", ev.title));
    body.appendChild(text("p", "meta", ev.when));
    body.appendChild(text("p", "meta", ev.place + (ev.external ? " · " + d.labelVia + " " + ev.external : "")));
    var link = text("a", "btn btn-blue btn-block", d.labelSee);
    link.href = ev.url;
    body.appendChild(link);
    box.appendChild(body);
    return box;
  }

  var byId = {};
  function load() {
    fetch(d.events, { headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var markers = [];
        data.events.forEach(function (ev) {
          var icon = L.divIcon({
            className: "pin tone-" + ev.tone + (ev.cancelled ? " is-cancelled" : ""),
            html: "<span class=\"pin-emoji\">" + ev.emoji + "</span>",
            iconSize: [40, 48], iconAnchor: [20, 46], popupAnchor: [0, -42]
          });
          var m = L.marker([ev.lat, ev.lon], { icon: icon, title: ev.title, keyboard: true });
          m.bindPopup(function () { return preview(ev); }, { maxWidth: 290, minWidth: 260, className: "ne-popup" });
          byId[ev.id] = m;
          markers.push(m);
        });
        cluster.addLayers(markers);
        if (status) status.textContent = data.events.length ? "" : d.labelEmpty;
        var wanted = byId[(location.hash || "").slice(1)];
        if (wanted) {
          cluster.zoomToShowLayer(wanted, function () { wanted.openPopup(); });
        } else if (markers.length && !location.search.match(/zone=nice/)) {
          var bounds = cluster.getBounds();
          if (bounds.isValid() && markers.length > 1) map.fitBounds(bounds.pad(0.05), { maxZoom: 13 });
        }
      })
      .catch(function () { if (status) status.textContent = d.labelEmpty; });
  }
  load();

  var locate = document.querySelector("[data-locate]");
  if (locate && navigator.geolocation) {
    locate.addEventListener("click", function () {
      navigator.geolocation.getCurrentPosition(function (pos) {
        var here = L.latLng(pos.coords.latitude, pos.coords.longitude);
        map.setView(region.contains(here) ? here : map.getCenter(), 14);
        L.circleMarker(here, { radius: 8, className: "me" }).addTo(map);
      });
    });
  } else if (locate) {
    locate.hidden = true;
  }
})();
