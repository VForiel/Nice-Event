// Page Découvrir : une carte à la fois. Glisser à droite (ou bouton étoile, flèche droite) = « Ça m'intéresse »,
// à gauche (croix, flèche gauche) = « Pas pour moi », toucher la carte (ou Entrée) = voir le détail.
// Les cartes suivantes sont demandées par paquets au serveur, qui les choisit d'après les choix déjà faits.
(function () {
  "use strict";

  var root = document.querySelector("[data-discover]");
  if (!root || !window.fetch) return;
  var d = root.dataset;
  var stack = root.querySelector("[data-stack]");
  var empty = root.querySelector("[data-empty]");
  var open = root.querySelector("[data-open]");
  var queue = [];
  var seen = [];
  var loading = false;
  var finished = false;
  var THRESHOLD = 100; // pixels de glissement pour valider

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  function build(ev) {
    var card = el("article", "swipe-card");
    var pic = el("div", "swipe-pic tone-" + ev.tone);
    if (ev.photo) {
      var img = document.createElement("img");
      img.src = ev.photo; img.alt = ""; img.draggable = false;
      pic.appendChild(img);
    } else {
      pic.appendChild(el("span", "", ev.category));
    }
    pic.appendChild(el("span", "swipe-stamp swipe-stamp-yes", d.labelYes));
    pic.appendChild(el("span", "swipe-stamp swipe-stamp-no", d.labelNo));
    card.appendChild(pic);
    var body = el("div", "swipe-body");
    var tags = el("div", "tags");
    if (ev.category) tags.appendChild(el("span", "tag tag-cat tone-" + ev.tone, ev.category));
    tags.appendChild(el("span", ev.free ? "tag tag-free" : "tag tag-price", ev.price));
    if (ev.source) tags.appendChild(el("span", "tag tag-ext", d.labelVia + " " + ev.source));
    body.appendChild(tags);
    body.appendChild(el("h2", "swipe-title", ev.title));
    body.appendChild(el("p", "meta", ev.when + " · " + ev.hours));
    body.appendChild(el("p", "meta", ev.place));
    if (ev.summary) body.appendChild(el("p", "swipe-summary", ev.summary));
    card.appendChild(body);
    card.event = ev;
    return card;
  }

  function current() { return stack.querySelector(".swipe-card:not(.is-next):not(.is-gone)"); }

  function render() {
    // Deux cartes dans la pile : celle du dessus et la suivante, en retrait.
    while (stack.querySelectorAll(".swipe-card:not(.is-gone)").length < 2 && queue.length) {
      var card = build(queue.shift());
      var top = current();
      if (top) card.classList.add("is-next");
      stack.insertBefore(card, stack.firstChild);
    }
    var top = current();
    if (!top) {
      var next = stack.querySelector(".swipe-card.is-next");
      if (next) { next.classList.remove("is-next"); top = next; }
    }
    if (top) open.href = top.event.url;
    empty.hidden = !!top || !finished;
    root.querySelectorAll("[data-choice], [data-open]").forEach(function (b) { b.toggleAttribute("disabled", !top); });
    if (queue.length < 3) more();
  }

  function more() {
    if (loading || finished) return;
    loading = true;
    var shown = Array.prototype.map.call(stack.querySelectorAll(".swipe-card"), function (c) { return c.event.id; });
    var ids = seen.concat(shown, queue.map(function (e) { return e.id; }));
    fetch(d.next + "?vus=" + ids.join(","), { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        loading = false;
        if (!data.events.length) finished = true;
        queue = queue.concat(data.events);
        render();
      })
      .catch(function () { loading = false; });
  }

  function decide(value) {
    var card = current();
    if (!card) return;
    var ev = card.event;
    seen.push(ev.id);
    var body = new FormData();
    body.set("value", value);
    body.set("keep", "1");
    fetch(ev.interest, { method: "POST", body: body, credentials: "same-origin",
      headers: { "X-CSRFToken": d.csrf, Accept: "application/json" } });
    card.classList.remove("is-dragging");
    card.classList.add("is-gone");
    card.style.transform = "translateX(" + (value === "yes" ? 140 : -140) + "%) rotate(" + (value === "yes" ? 18 : -18) + "deg)";
    card.style.opacity = "0";
    setTimeout(function () { card.remove(); }, 300);
    var next = stack.querySelector(".swipe-card.is-next");
    if (next) next.classList.remove("is-next");
    render();
  }

  // Glisser (doigt, souris ou stylet)
  var start = null;
  stack.addEventListener("pointerdown", function (e) {
    var card = current();
    if (!card || !card.contains(e.target)) return;
    start = { x: e.clientX, y: e.clientY, card: card, moved: false };
    card.setPointerCapture(e.pointerId);
    card.classList.add("is-dragging");
  });
  stack.addEventListener("pointermove", function (e) {
    if (!start) return;
    var dx = e.clientX - start.x;
    if (Math.abs(dx) > 6) start.moved = true;
    start.card.style.transform = "translateX(" + dx + "px) rotate(" + dx / 18 + "deg)";
    start.card.querySelector(".swipe-stamp-yes").style.opacity = Math.max(0, Math.min(1, dx / THRESHOLD));
    start.card.querySelector(".swipe-stamp-no").style.opacity = Math.max(0, Math.min(1, -dx / THRESHOLD));
  });
  function release(e) {
    if (!start) return;
    var dx = e.clientX - start.x;
    var card = start.card, moved = start.moved;
    start = null;
    if (dx > THRESHOLD) return decide("yes");
    if (dx < -THRESHOLD) return decide("no");
    card.classList.remove("is-dragging");
    card.style.transform = "";
    card.querySelectorAll(".swipe-stamp").forEach(function (s) { s.style.opacity = ""; });
    if (!moved && e.type === "pointerup") location.href = card.event.url; // simple toucher : le détail
  }
  stack.addEventListener("pointerup", release);
  stack.addEventListener("pointercancel", release);

  root.querySelectorAll("[data-choice]").forEach(function (b) {
    b.addEventListener("click", function () { decide(b.dataset.choice); });
  });
  document.addEventListener("keydown", function (e) {
    if (e.target.closest("input, textarea, select")) return;
    if (e.key === "ArrowRight") decide("yes");
    else if (e.key === "ArrowLeft") decide("no");
    else if (e.key === "Enter" && current() && !e.target.closest("a, button")) location.href = current().event.url;
  });

  more();
})();
