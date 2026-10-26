// Filtre avancé (agenda et carte) : éditeur de règles ET / OU / SAUF, envoyé au serveur dans ?regle=… (JSON),
// règles enregistrées sur le compte (membres connectés) ou dans le navigateur (visiteurs).
(function () {
  "use strict";

  var root = document.querySelector("[data-rule-builder]");
  var input = document.querySelector("[data-rule-input]");
  var specNode = document.getElementById("filter-spec");
  if (!root || !input || !specNode) return;
  var spec = JSON.parse(specNode.textContent);
  var L = spec.labels;
  var form = input.form;
  var LOCAL_KEY = "ne-filtres";

  var MULTI = { categorie: 1, zone: 1, commune: 1, source: 1, prix: 1, public: 1, jour: 1 };
  var fieldNames = {};
  spec.fields.forEach(function (f) { fieldNames[f[0]] = f[1]; });

  function parse(text) {
    try {
      var r = JSON.parse(text);
      return r && typeof r === "object" ? r : null;
    } catch (e) { return null; }
  }
  function group(rule) {
    if (!rule) return { op: "and", rules: [] };
    return rule.rules ? rule : { op: "and", rules: [rule] };
  }
  var state = group(parse(input.value));

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function button(text, cls, onClick) {
    var b = el("button", "btn btn-ghost btn-sm " + (cls || ""), text);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }
  function select(options, value, onChange, cls) {
    var s = el("select", cls);
    options.forEach(function (o) {
      var opt = el("option", null, o[1]);
      opt.value = o[0];
      if (String(o[0]) === String(value)) opt.selected = true;
      s.appendChild(opt);
    });
    s.addEventListener("change", function () { onChange(s.value); });
    return s;
  }
  function number(value, attrs, onChange) {
    var i = el("input");
    i.type = "number";
    Object.keys(attrs).forEach(function (k) { i.setAttribute(k, attrs[k]); });
    if (value != null && value !== "") i.value = value;
    i.addEventListener("input", function () { onChange(i.value === "" ? null : Number(i.value)); });
    return i;
  }
  function notToggle(node) {
    var label = el("label", "rule-not");
    label.title = L.notTitle;
    var box = el("input");
    box.type = "checkbox";
    box.checked = !!node.not;
    box.addEventListener("change", function () { node.not = box.checked; });
    label.appendChild(box);
    label.appendChild(document.createTextNode(" " + L.not));
    return label;
  }

  // Valeurs d'une condition ------------------------------------------------------------------------------------
  function checklist(node, options) {
    var box = el("div", "rule-checks");
    node.in = node.in || [];
    var list = el("div", "rule-checks-list");
    if (options.length > 12) {
      var find = el("input", "rule-find");
      find.type = "search";
      find.placeholder = L.search;
      find.addEventListener("input", function () {
        var q = find.value.toLowerCase();
        list.querySelectorAll("label").forEach(function (lab) {
          lab.hidden = q && lab.textContent.toLowerCase().indexOf(q) === -1;
        });
      });
      box.appendChild(find);
    }
    options.forEach(function (o) {
      var lab = el("label");
      var c = el("input");
      c.type = "checkbox";
      c.value = o[0];
      c.checked = node.in.indexOf(String(o[0])) !== -1;
      c.addEventListener("change", function () {
        node.in = node.in.filter(function (v) { return v !== c.value; });
        if (c.checked) node.in.push(c.value);
      });
      lab.appendChild(c);
      lab.appendChild(document.createTextNode(" " + o[1]));
      list.appendChild(lab);
    });
    box.appendChild(list);
    return box;
  }

  function proximity(node) {
    var box = el("div", "rule-inline");
    box.appendChild(number(node.km || 5, { min: "0.5", max: "200", step: "0.5", "aria-label": "km" },
      function (v) { node.km = v; }));
    box.appendChild(el("span", null, L.km));
    var places = [["", node.label && node.lat ? node.label : L.choosePlace]].concat(
      spec.places.map(function (p, i) { return [String(i), p[0]]; }));
    var where = select(places, "", function (v) {
      if (v === "") return;
      var p = spec.places[Number(v)];
      node.lat = p[1]; node.lon = p[2]; node.label = p[0];
    });
    box.appendChild(where);
    function setPoint(lat, lon, label) {
      node.lat = Math.round(lat * 1e5) / 1e5;
      node.lon = Math.round(lon * 1e5) / 1e5;
      node.label = label;
      where.options[0].textContent = label;
      where.value = "";
    }
    if (navigator.geolocation) {
      box.appendChild(button(L.here, "", function () {
        navigator.geolocation.getCurrentPosition(function (pos) {
          setPoint(pos.coords.latitude, pos.coords.longitude, L.here);
        });
      }));
    }
    if (window.neMap) {
      box.appendChild(button(L.mapCenter, "", function () {
        var c = window.neMap.getCenter();
        setPoint(c.lat, c.lng, L.mapCenter);
      }));
    }
    if (!node.km) node.km = 5;
    return box;
  }

  function values(node) {
    var f = node.field;
    if (MULTI[f]) return checklist(node, spec[f]);
    if (f === "quand") {
      if (!node.value) node.value = spec.quand[0][0];
      return select(spec.quand, node.value, function (v) { node.value = v; });
    }
    if (f === "heure") {
      var h = el("div", "rule-inline");
      h.appendChild(el("span", null, L.from));
      h.appendChild(number(node.min, { min: "0", max: "23", "aria-label": L.from }, function (v) { node.min = v; }));
      h.appendChild(el("span", null, L.hour + " " + L.to));
      h.appendChild(number(node.max, { min: "0", max: "23", "aria-label": L.to }, function (v) { node.max = v; }));
      h.appendChild(el("span", null, L.hour));
      return h;
    }
    if (f === "prix_max" || f === "age") {
      var n = el("div", "rule-inline");
      n.appendChild(number(node.value, f === "age" ? { min: "0", max: "120" } : { min: "0", step: "0.5" },
        function (v) { node.value = v; }));
      n.appendChild(el("span", null, f === "age" ? L.years : L.euros));
      return n;
    }
    if (f === "texte") {
      var t = el("input");
      t.type = "text";
      t.placeholder = L.words;
      t.value = node.value || "";
      t.addEventListener("input", function () { node.value = t.value; });
      return t;
    }
    if (f === "proximite") return proximity(node);
    return el("span");
  }

  // Arbre ------------------------------------------------------------------------------------------------------
  function renderLeaf(node, parent) {
    var row = el("div", "rule-row");
    var head = el("div", "rule-head");
    head.appendChild(notToggle(node));
    head.appendChild(select(spec.fields, node.field, function (v) {
      Object.keys(node).forEach(function (k) { if (k !== "not") delete node[k]; });
      node.field = v;
      render();
    }, "rule-field"));
    head.appendChild(button("×", "rule-remove", function () {
      parent.rules.splice(parent.rules.indexOf(node), 1);
      render();
    }));
    head.lastChild.setAttribute("aria-label", L.remove);
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
      head.appendChild(button("×", "rule-remove", function () {
        parent.rules.splice(parent.rules.indexOf(node), 1);
        render();
      }));
      head.lastChild.setAttribute("aria-label", L.remove);
    }
    box.appendChild(head);
    var list = el("div", "rule-list");
    if (!node.rules.length) list.appendChild(el("p", "help", L.empty));
    node.rules.forEach(function (child) {
      list.appendChild(child.rules ? renderGroup(child, node, depth + 1) : renderLeaf(child, node));
    });
    box.appendChild(list);
    var add = el("div", "rule-add");
    add.appendChild(button("+ " + L.addRule, "", function () {
      node.rules.push({ field: "categorie", in: [] });
      render();
    }));
    if (depth < 3) {
      add.appendChild(button("+ " + L.addGroup, "", function () {
        node.rules.push({ op: "or", rules: [{ field: "categorie", in: [] }] });
        render();
      }));
    }
    box.appendChild(add);
    return box;
  }

  // Conditions vides (aucune case cochée…) retirées avant l'envoi.
  function prune(node) {
    if (node.rules) {
      var kept = node.rules.map(prune).filter(Boolean);
      if (!kept.length) return null;
      var out = { op: node.op || "and", rules: kept };
      if (node.not) out.not = true;
      return out;
    }
    if (MULTI[node.field] && !(node.in && node.in.length)) return null;
    if ((node.field === "prix_max" || node.field === "age" || node.field === "texte") && (node.value == null || node.value === "")) return null;
    if (node.field === "heure" && node.min == null && node.max == null) return null;
    if (node.field === "proximite" && node.lat == null) return null;
    return JSON.parse(JSON.stringify(node));
  }

  function submit(rule) {
    input.value = rule ? JSON.stringify(rule) : "";
    input.disabled = !rule;
    var page = form.querySelector("input[name=page]");
    if (page) page.disabled = true;
    form.submit();
  }

  // Règles enregistrées ----------------------------------------------------------------------------------------
  var savedBox = el("div", "rule-saved");

  function localList() {
    try { return JSON.parse(localStorage.getItem(LOCAL_KEY)) || []; } catch (e) { return []; }
  }
  function storeLocal(list) {
    try { localStorage.setItem(LOCAL_KEY, JSON.stringify(list)); } catch (e) { /* stockage indisponible */ }
  }
  function savedList() {
    return spec.saved ? spec.saved : localList();
  }

  function post(url, data) {
    var body = new URLSearchParams(data);
    return fetch(url, { method: "POST", body: body, credentials: "same-origin",
      headers: { "X-CSRFToken": root.dataset.csrf, Accept: "application/json" } })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || L.error); return j; }); });
  }

  function save() {
    var rule = prune(state);
    if (!rule) { window.alert(L.empty); return; }
    var name = (window.prompt(L.namePrompt) || "").trim();
    if (!name) return;
    if (spec.saved) {
      post(root.dataset.saveUrl, { name: name, rule: JSON.stringify(rule) }).then(function (item) {
        spec.saved = spec.saved.filter(function (s) { return s.name !== item.name; }).concat([item]);
        renderSaved();
      }).catch(function (e) { window.alert(e.message); });
    } else {
      var list = localList().filter(function (s) { return s.name !== name; });
      list.push({ id: "local-" + Date.now(), name: name, rule: rule });
      storeLocal(list);
      renderSaved();
    }
  }

  function remove(item) {
    if (!window.confirm(L.deleteConfirm)) return;
    if (spec.saved) {
      post(root.dataset.deleteUrl.replace("/0/", "/" + item.id + "/"), {}).then(function () {
        spec.saved = spec.saved.filter(function (s) { return s.id !== item.id; });
        renderSaved();
      }).catch(function (e) { window.alert(e.message); });
    } else {
      storeLocal(localList().filter(function (s) { return s.id !== item.id; }));
      renderSaved();
    }
  }

  function renderSaved() {
    savedBox.innerHTML = "";
    savedBox.appendChild(el("p", "filter-label", L.saved));
    var list = savedList().slice().sort(function (a, b) { return a.name.localeCompare(b.name); });
    if (!list.length) {
      savedBox.appendChild(el("p", "help", L.noSaved));
    }
    var ul = el("ul", "rule-saved-list");
    list.forEach(function (item) {
      var li = el("li");
      li.appendChild(el("span", "rule-saved-name", item.name));
      li.appendChild(button(L.load, "", function () { state = group(item.rule); submit(prune(state)); }));
      li.appendChild(button(L.delete, "", function () { remove(item); }));
      ul.appendChild(li);
    });
    savedBox.appendChild(ul);
    if (!spec.saved) savedBox.appendChild(el("p", "help", L.local));
  }

  // Rendu ------------------------------------------------------------------------------------------------------
  var tree = el("div", "rule-tree");
  var actions = el("div", "rule-actions");
  var apply = button(L.apply, "btn-blue", function () { submit(prune(state)); });
  apply.classList.remove("btn-ghost");
  actions.appendChild(apply);
  actions.appendChild(button(L.clear, "", function () { state = group(null); submit(null); }));
  actions.appendChild(button(L.save, "", save));

  function render() {
    tree.innerHTML = "";
    tree.appendChild(renderGroup(state, null, 0));
  }

  root.innerHTML = "";
  root.appendChild(tree);
  root.appendChild(actions);
  root.appendChild(savedBox);
  render();
  renderSaved();

  // Champ vide : pas de « regle= » dans l'adresse quand on cherche ou qu'on change de puce.
  form.addEventListener("submit", function () { if (!input.value) input.disabled = true; });
})();
