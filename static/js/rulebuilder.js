// Page « Filtres & alertes » : éditeur de règles ET / OU / SAUF, aperçu en direct, filtres enregistrés et alertes,
// notifications du navigateur. Aucun clic ne recharge la page (sauf « Voir dans l'agenda / sur la carte »).
(function () {
  "use strict";

  var root = document.querySelector("[data-rule-builder]");
  var specNode = document.getElementById("rule-spec");
  if (!root || !specNode) return;
  var spec = JSON.parse(specNode.textContent);
  var L = spec.labels;
  var nameInput = document.querySelector("[data-rule-name]");
  var MULTI = { categorie: 1, zone: 1, commune: 1, source: 1, prix: 1, public: 1, langue: 1, jour: 1 };
  var FIELD = {};
  spec.fields.forEach(function (f) { FIELD[f[0]] = { label: f[1], hint: f[2] }; });
  var editing = root.dataset.editing ? Number(root.dataset.editing) : null;

  function group(rule) {
    if (!rule || typeof rule !== "object") return { op: "and", rules: [] };
    return rule.rules ? rule : { op: "and", rules: [rule] };
  }
  var current = document.getElementById("rule-current");
  var state = group(current ? JSON.parse(current.textContent) : null);

  // Petits outils ---------------------------------------------------------------------------------------------------
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function button(text, cls, onClick) {
    var b = el("button", cls || "btn btn-ghost btn-sm", text);
    b.type = "button";
    b.addEventListener("click", function (e) { e.preventDefault(); onClick(e); });
    return b;
  }
  function fold(s) { return String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
  function number(value, attrs, onInput) {
    var i = el("input");
    i.type = "number";
    Object.keys(attrs).forEach(function (k) { i.setAttribute(k, attrs[k]); });
    if (value != null && value !== "") i.value = value;
    i.addEventListener("input", function () { onInput(i.value === "" ? null : Number(i.value)); changed(); });
    return i;
  }
  function select(options, value, onChange) {
    var s = el("select");
    options.forEach(function (o) {
      var opt = el("option", null, o[1]);
      opt.value = o[0];
      if (String(o[0]) === String(value)) opt.selected = true;
      s.appendChild(opt);
    });
    s.addEventListener("change", function () { onChange(s.value); changed(); });
    return s;
  }
  function notToggle(node) {
    var label = el("label", "rule-not");
    label.title = L.notTitle;
    var box = el("input");
    box.type = "checkbox";
    box.checked = !!node.not;
    box.addEventListener("change", function () { node.not = box.checked; label.classList.toggle("on", box.checked); changed(); });
    label.classList.toggle("on", !!node.not);
    label.appendChild(box);
    label.appendChild(document.createTextNode(" " + L.not));
    return label;
  }

  // Éditeurs de valeurs -------------------------------------------------------------------------------------------
  function checklist(node, options) {
    var box = el("div", "rule-checks");
    node.in = node.in || [];
    var list = el("div", "rule-checks-list");
    if (options.length > 12) {
      var find = el("input", "rule-find");
      find.type = "search";
      find.placeholder = L.search;
      find.addEventListener("input", function () {
        var q = fold(find.value);
        list.querySelectorAll("label").forEach(function (lab) { lab.hidden = q && fold(lab.textContent).indexOf(q) === -1; });
      });
      box.appendChild(find);
    }
    options.forEach(function (o) {
      var lab = el("label", "dd-check");
      var c = el("input");
      c.type = "checkbox";
      c.value = o[0];
      c.checked = node.in.indexOf(String(o[0])) !== -1;
      c.addEventListener("change", function () {
        node.in = node.in.filter(function (v) { return v !== c.value; });
        if (c.checked) node.in.push(c.value);
        changed();
      });
      lab.appendChild(c);
      lab.appendChild(document.createTextNode(" " + o[1]));
      list.appendChild(lab);
    });
    box.appendChild(list);
    return box;
  }

  function address(node) {
    var box = el("div", "rule-inline rule-address");
    if (!node.km) node.km = 5;
    box.appendChild(number(node.km, { min: "0.5", max: "200", step: "0.5", "aria-label": "km" }, function (v) { node.km = v; }));
    box.appendChild(el("span", null, L.km));
    var wrap = el("div", "autocomplete");
    var input = el("input");
    input.type = "search";
    input.placeholder = L.address;
    input.value = node.label || "";
    var list = el("ul", "suggestions");
    list.hidden = true;
    wrap.appendChild(input);
    wrap.appendChild(list);
    box.appendChild(wrap);
    var wait = null;
    function pick(r) {
      node.lat = Math.round(r.lat * 1e5) / 1e5; node.lon = Math.round(r.lon * 1e5) / 1e5; node.label = r.label;
      input.value = r.label; list.hidden = true; list.innerHTML = ""; changed();
    }
    input.addEventListener("input", function () {
      clearTimeout(wait);
      delete node.lat; delete node.lon;
      var q = input.value.trim();
      if (q.length < 3) { list.hidden = true; return; }
      wait = setTimeout(function () {
        fetch(spec.urls.geocode + "?q=" + encodeURIComponent(q)).then(function (r) { return r.json(); }).then(function (data) {
          list.innerHTML = "";
          (data.results || []).forEach(function (r) {
            var li = el("li", null, r.label);
            li.setAttribute("role", "option");
            li.addEventListener("mousedown", function (e) { e.preventDefault(); pick(r); });
            list.appendChild(li);
          });
          list.hidden = !list.children.length;
        }).catch(function () { list.hidden = true; });
      }, 250);
    });
    input.addEventListener("blur", function () { setTimeout(function () { list.hidden = true; }, 150); });
    if (navigator.geolocation) {
      box.appendChild(button(L.here, "dd-link", function () {
        navigator.geolocation.getCurrentPosition(function (pos) {
          pick({ lat: pos.coords.latitude, lon: pos.coords.longitude, label: L.here });
        });
      }));
    }
    return box;
  }

  function regex(node) {
    var box = el("div", "rule-regex");
    var input = el("input");
    input.type = "text";
    input.className = "mono";
    input.spellcheck = false;
    input.placeholder = "\\bski|randonn";
    input.value = node.value || "";
    var status = el("p", "help rule-regex-status");
    function check() {
      try { new RegExp(input.value, "i"); status.textContent = ""; input.classList.remove("is-bad"); }
      catch (e) { status.textContent = L.regexBad + " : " + e.message; input.classList.add("is-bad"); }
    }
    input.addEventListener("input", function () { node.value = input.value; check(); changed(); });
    box.appendChild(input);
    var help = el("p", "help", L.regexHelp + " ");
    [["ski", "ski"], ["\\bski\\b", "\\bski\\b"], ["jazz|blues", "jazz|blues"], ["^Atelier", "^Atelier"]].forEach(function (ex) {
      var code = el("button", "code-chip", ex[1]);
      code.type = "button";
      code.addEventListener("click", function () { input.value = ex[0]; node.value = ex[0]; check(); changed(); });
      help.appendChild(code);
    });
    box.appendChild(help);
    box.appendChild(status);
    check();
    return box;
  }

  function values(node) {
    var f = node.field;
    if (MULTI[f]) return checklist(node, spec[f]);
    var row = el("div", "rule-inline");
    if (f === "quand") {
      if (!node.value) node.value = spec.quand[0][0];
      row.appendChild(select(spec.quand, node.value, function (v) { node.value = v; }));
    } else if (f === "dates") {
      [["from", L.dateFrom], ["to", L.dateTo]].forEach(function (p) {
        row.appendChild(el("span", null, p[1]));
        var d = el("input");
        d.type = "date";
        d.min = spec.today;
        d.value = node[p[0]] || "";
        d.addEventListener("change", function () { node[p[0]] = d.value; changed(); });
        row.appendChild(d);
      });
    } else if (f === "heure") {
      row.appendChild(el("span", null, L.hourFrom));
      row.appendChild(number(node.min, { min: "0", max: "23" }, function (v) { node.min = v; }));
      row.appendChild(el("span", null, L.hourTo));
      row.appendChild(number(node.max, { min: "0", max: "23" }, function (v) { node.max = v; }));
      row.appendChild(el("span", null, L.hour));
    } else if (f === "age_range") {
      row.appendChild(el("span", null, L.ageFrom));
      row.appendChild(number(node.min, { min: "0", max: "120" }, function (v) { node.min = v; }));
      row.appendChild(el("span", null, L.to));
      row.appendChild(number(node.max, { min: "0", max: "120" }, function (v) { node.max = v; }));
      row.appendChild(el("span", null, L.years));
    } else if (f === "prix_max") {
      row.appendChild(number(node.value, { min: "0", step: "0.5" }, function (v) { node.value = v; }));
      row.appendChild(el("span", null, L.euros));
    } else if (f === "texte") {
      var t = el("input");
      t.type = "text";
      t.placeholder = L.words;
      t.value = node.value || "";
      t.addEventListener("input", function () { node.value = t.value; changed(); });
      row.appendChild(t);
    } else if (f === "regex") {
      return regex(node);
    } else if (f === "proximite") {
      return address(node);
    } else if (f === "accessible") {
      row.appendChild(el("span", "help", L.accessible));
    }
    return row;
  }

  // Choix du critère : liste défilante filtrable (« âge », « type=prix ») ---------------------------------------------
  function picker(onPick) {
    var box = el("div", "rule-picker");
    var input = el("input");
    input.type = "search";
    input.placeholder = L.pickFilter;
    input.setAttribute("aria-label", L.pick);
    var list = el("ul", "rule-picker-list");
    list.setAttribute("role", "listbox");
    var none = el("li", "help", L.noField);
    // Pertinence : début du nom, début d'un mot du nom ou de la clé, début d'un mot de l'explication, sinon morceau.
    function score(f, q) {
      if (!q) return 0;
      var label = fold(f[1]);
      var words = function (s) { return s.split(/[^a-z0-9€]+/); };
      var starts = function (s) { return words(s).some(function (w) { return w.indexOf(q) === 0; }); };
      if (label.indexOf(q) === 0) return 1;
      if (starts(label) || fold(f[0]).indexOf(q) === 0) return 2;
      if (starts(fold(f[2]))) return 3;
      return fold(f[0] + " " + f[1] + " " + f[2]).indexOf(q) !== -1 ? 4 : 0;
    }
    function fill() {
      var q = fold(input.value.replace(/^\s*type\s*=\s*/i, "").trim());
      list.innerHTML = "";
      spec.fields.map(function (f, i) { return { f: f, s: score(f, q), i: i }; })
        .filter(function (x) { return !q || x.s; })
        .sort(function (a, b) { return (a.s - b.s) || (a.i - b.i); })
        .forEach(function (x) {
        var f = x.f;
        var li = el("li");
        var b = el("button", "rule-picker-item");
        b.type = "button";
        b.appendChild(el("b", null, f[1]));
        b.appendChild(el("span", null, f[2]));
        b.addEventListener("click", function () { onPick(f[0]); });
        li.appendChild(b);
        list.appendChild(li);
      });
      if (!list.children.length) list.appendChild(none);
    }
    input.addEventListener("input", fill);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        var first = list.querySelector("button");
        if (first) first.click();
      } else if (e.key === "Escape") {
        box.remove();
      }
    });
    box.appendChild(input);
    box.appendChild(list);
    fill();
    setTimeout(function () { input.focus({ preventScroll: true }); }, 0);
    return box;
  }

  // Arbre ------------------------------------------------------------------------------------------------------------
  function removeFrom(parent, node) {
    parent.rules.splice(parent.rules.indexOf(node), 1);
    render();
    changed();
  }

  function renderLeaf(node, parent) {
    var row = el("div", "rule-row" + (node.not ? " is-not" : ""));
    var head = el("div", "rule-head");
    head.appendChild(notToggle(node));
    var info = FIELD[node.field] || { label: node.field, hint: "" };
    head.appendChild(el("b", "rule-label", info.label));
    var remove = button("×", "rule-remove", function () { removeFrom(parent, node); });
    remove.setAttribute("aria-label", L.remove + " : " + info.label);
    head.appendChild(remove);
    row.appendChild(head);
    row.appendChild(values(node));
    return row;
  }

  function renderGroup(node, parent, depth) {
    var box = el("div", "rule-group" + (depth ? " rule-subgroup" : ""));
    var head = el("div", "rule-head");
    if (depth) head.appendChild(notToggle(node));
    head.appendChild(select([["and", L.and], ["or", L.or]], node.op || "and", function (v) { node.op = v; }));
    if (parent) {
      var remove = button("×", "rule-remove", function () { removeFrom(parent, node); });
      remove.setAttribute("aria-label", L.remove);
      head.appendChild(remove);
    }
    box.appendChild(head);
    var list = el("div", "rule-list");
    if (!node.rules.length) list.appendChild(el("p", "help", L.empty));
    node.rules.forEach(function (child) {
      list.appendChild(child.rules ? renderGroup(child, node, depth + 1) : renderLeaf(child, node));
    });
    box.appendChild(list);
    var add = el("div", "rule-add");
    var open = null;
    add.appendChild(button("+ " + L.addRule, "btn btn-ghost btn-sm", function () {
      if (open) { open.remove(); open = null; return; }
      open = picker(function (field) {
        var leaf = { field: field };
        if (MULTI[field]) leaf.in = [];
        node.rules.push(leaf);
        render();
        changed();
      });
      add.appendChild(open);
    }));
    if (depth < 3) {
      add.appendChild(button("+ " + L.addGroup, "btn btn-ghost btn-sm", function () {
        node.rules.push({ op: "or", rules: [] });
        render();
      }));
    }
    box.appendChild(add);
    return box;
  }

  function render() {
    root.innerHTML = "";
    root.appendChild(renderGroup(state, null, 0));
  }

  // Règle propre à envoyer : conditions incomplètes retirées ---------------------------------------------------------
  function prune(node) {
    if (node.rules) {
      var kept = node.rules.map(prune).filter(Boolean);
      if (!kept.length) return null;
      var out = { op: node.op || "and", rules: kept };
      if (node.not) out.not = true;
      return out;
    }
    var f = node.field;
    if (MULTI[f] && !(node.in && node.in.length)) return null;
    if ((f === "prix_max" || f === "texte" || f === "regex") && (node.value == null || node.value === "")) return null;
    if ((f === "heure" || f === "age_range") && node.min == null && node.max == null) return null;
    if (f === "dates" && !node.from && !node.to) return null;
    if (f === "proximite" && node.lat == null) return null;
    return JSON.parse(JSON.stringify(node));
  }

  // Aperçu ------------------------------------------------------------------------------------------------------------
  var countEl = document.querySelector("[data-preview-count]");
  var listEl = document.querySelector("[data-preview-list]");
  var errorsEl = document.querySelector("[data-preview-errors]");
  var timer = null;
  var pending = null;
  function changed() {
    clearTimeout(timer);
    timer = setTimeout(preview, 350);
  }
  function preview() {
    var rule = prune(state);
    listEl.innerHTML = "";
    errorsEl.innerHTML = "";
    if (!rule) { countEl.textContent = L.incomplete; return; }
    if (pending) pending.abort();
    pending = new AbortController();
    fetch(spec.urls.preview + "?regle=" + encodeURIComponent(JSON.stringify(rule)), { signal: pending.signal })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        (data.errors || []).forEach(function (msg) { errorsEl.appendChild(el("li", null, msg)); });
        if (data.count == null) { countEl.textContent = data.errors && data.errors.length ? "" : L.incomplete; return; }
        countEl.textContent = data.count === 0 ? L.count0 : data.count === 1 ? L.count1 : L.countN.replace("%(n)s", data.count);
        (data.events || []).forEach(function (ev) {
          var li = el("li");
          var a = el("a", null, ev.title);
          a.href = ev.url;
          li.appendChild(a);
          li.appendChild(el("span", "help", " " + ev.when + " · " + ev.place));
          listEl.appendChild(li);
        });
      })
      .catch(function () { /* remplacée par une requête plus récente */ });
  }

  // Utiliser dans l'agenda / la carte ---------------------------------------------------------------------------------
  var useForm = document.querySelector("[data-use-form]");
  if (useForm) {
    useForm.addEventListener("submit", function (e) {
      var rule = prune(state);
      if (!rule) { e.preventDefault(); countEl.textContent = L.incomplete; countEl.scrollIntoView({ block: "nearest", behavior: "smooth" }); return; }
      useForm.querySelector("[data-use-rule]").value = JSON.stringify(rule);
      useForm.querySelector("[data-use-name]").value = nameInput.value;
    });
  }

  // Exemples du tuto ------------------------------------------------------------------------------------------------
  document.querySelectorAll("[data-example]").forEach(function (b) {
    b.addEventListener("click", function () {
      state = group(JSON.parse(b.dataset.example));
      nameInput.value = b.textContent.trim();
      setEditing(null);
      render();
      changed();
      root.closest(".builder-card").scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  // Enregistrement et alertes (membres) -----------------------------------------------------------------------------
  var csrf = root.dataset.csrf;
  function post(url, data) {
    return fetch(url, { method: "POST", body: new URLSearchParams(data), credentials: "same-origin",
      headers: { "X-CSRFToken": csrf, Accept: "application/json" } })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || L.error); return j; }); });
  }
  var saveBtn = document.querySelector("[data-save]");
  var saveLabel = document.querySelector("[data-save-label]");
  var saveStatus = document.querySelector("[data-save-status]");
  var saveAlert = document.querySelector("[data-save-alert]");
  var saveFrequency = document.querySelector("[data-save-frequency]");
  var newBtn = document.querySelector("[data-new]");

  function setEditing(id, name) {
    editing = id;
    if (saveLabel) saveLabel.textContent = id ? L.update : L.saveNew;
    if (newBtn) newBtn.hidden = !id;
    if (saveStatus) saveStatus.textContent = id ? L.editing.replace("%(name)s", name || "") : "";
    document.querySelectorAll("[data-saved-id]").forEach(function (card) {
      card.classList.toggle("is-editing", Number(card.dataset.savedId) === id);
    });
  }

  function refreshSaved() {
    return fetch(location.pathname, { headers: { Accept: "text/html" } }).then(function (r) { return r.text(); }).then(function (html) {
      var doc = new DOMParser().parseFromString(html, "text/html");
      var fresh = doc.querySelector("[data-saved-section]");
      var section = document.querySelector("[data-saved-section]");
      if (fresh && section) { section.innerHTML = fresh.innerHTML; bindSaved(); setEditing(editing, nameInput.value); }
    });
  }

  if (saveBtn) {
    saveBtn.addEventListener("click", function () {
      var rule = prune(state);
      var name = nameInput.value.trim();
      if (!name) { saveStatus.textContent = L.nameMissing; nameInput.focus(); return; }
      if (!rule) { saveStatus.textContent = L.incomplete; return; }
      saveBtn.disabled = true;
      post(spec.urls.save, { id: editing || "", name: name, rule: JSON.stringify(rule),
        alert: saveAlert.checked ? "1" : "0", frequency: saveFrequency.value })
        .then(function (item) {
          setEditing(item.id, item.name);
          return refreshSaved().then(function () { saveStatus.textContent = L.saved; });
        })
        .catch(function (err) { saveStatus.textContent = err.message; })
        .then(function () { saveBtn.disabled = false; });
    });
  }
  if (newBtn) {
    newBtn.addEventListener("click", function () {
      state = group(null); nameInput.value = ""; saveAlert.checked = false;
      setEditing(null); render(); changed();
    });
  }

  function bindSaved() {
    document.querySelectorAll("[data-saved-id]").forEach(function (card) {
      var id = Number(card.dataset.savedId);
      var toggle = card.querySelector("[data-alert-toggle]");
      var freq = card.querySelector("[data-alert-frequency]");
      var update = function () {
        post(spec.urls.save + id + "/alerte/",
          { alert: toggle.checked ? "1" : "0", frequency: freq.value })
          .then(function (item) {
            card.classList.toggle("has-alert", item.alert);
            card.dataset.savedAlert = item.alert ? "1" : "";
            card.dataset.savedFrequency = item.frequency;
            var help = card.querySelector(".saved-main .help");
            help.textContent = item.alert ? "🔔 " + freq.options[freq.selectedIndex].text : L.noAlert;
          })
          .catch(function (err) { window.alert(err.message); });
      };
      toggle.addEventListener("change", update);
      freq.addEventListener("change", update);
      card.querySelector("[data-edit]").addEventListener("click", function () {
        state = group(JSON.parse(card.dataset.savedRule));
        nameInput.value = card.dataset.savedName;
        saveAlert.checked = !!card.dataset.savedAlert;
        saveFrequency.value = card.dataset.savedFrequency;
        setEditing(id, card.dataset.savedName);
        render();
        changed();
        root.closest(".builder-card").scrollIntoView({ behavior: "smooth", block: "start" });
      });
      card.querySelector("[data-delete]").addEventListener("click", function () {
        if (!window.confirm(L.deleteConfirm)) return;
        post(spec.urls.save + id + "/supprimer/", {}).then(function () {
          card.remove();
          if (editing === id) setEditing(null);
        }).catch(function (err) { window.alert(err.message); });
      });
    });
  }
  bindSaved();

  // Notifications du navigateur ---------------------------------------------------------------------------------------
  var channels = document.querySelector("[data-channels]");
  var pushToggle = document.querySelector("[data-push-toggle]");
  if (channels && pushToggle) {
    var pushStatus = document.querySelector("[data-push-status]");
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      pushToggle.disabled = true;
    } else {
      pushToggle.addEventListener("change", function () {
        if (!pushToggle.checked) return;
        var key = channels.dataset.vapid;
        var raw = atob(key.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((key.length + 3) % 4));
        var bytes = new Uint8Array(raw.length);
        for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
        navigator.serviceWorker.register("/sw.js").then(function (reg) {
          return Notification.requestPermission().then(function (perm) {
            if (perm !== "granted") throw new Error(L.pushDenied);
            return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: bytes });
          });
        }).then(function (sub) {
          return fetch(channels.dataset.pushUrl, { method: "POST", body: JSON.stringify(sub.toJSON()), credentials: "same-origin",
            headers: { "X-CSRFToken": csrf, "Content-Type": "application/json" } });
        }).then(function () { pushStatus.textContent = L.pushOn; })
          .catch(function (err) { pushToggle.checked = false; pushStatus.textContent = err.message; });
      });
    }
  }

  if (editing) {
    var card = document.querySelector("[data-saved-id='" + editing + "']");
    setEditing(editing, card ? card.dataset.savedName : nameInput.value);
  }
  render();
  preview();
})();
