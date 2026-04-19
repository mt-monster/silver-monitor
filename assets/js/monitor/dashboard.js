/**
 * dashboard.js — 商品全品类看板
 * 从 /api/instruments 获取全部品种行情，按分类渲染为紧凑卡片网格。
 */
(function () {
  var Monitor = window.Monitor;
  if (!Monitor) return;

  var _catOrder = {
    precious_metals: { name: "贵金属", icon: "💎", order: 0 },
    base_metals:     { name: "有色金属", icon: "🔩", order: 1 },
    ferrous:         { name: "黑色系", icon: "⚙️", order: 2 },
    energy:          { name: "能源化工", icon: "🛢️", order: 3 },
    agriculture:     { name: "农产品", icon: "🌾", order: 4 },
    international:   { name: "国际", icon: "🌍", order: 5 }
  };

  var _activeCat = "all"; // "all" or category key

  /* ── Category filter bar ── */
  function buildCatBar(categories) {
    var bar = document.getElementById("dashCatBar");
    if (!bar) return;
    bar.innerHTML = "";

    var allBtn = document.createElement("button");
    allBtn.className = "dash-cat-btn" + (_activeCat === "all" ? " active" : "");
    allBtn.textContent = "全部";
    allBtn.onclick = function () { _activeCat = "all"; Monitor.fetchDashboard(); };
    bar.appendChild(allBtn);

    var cats = Object.keys(categories || _catOrder);
    cats.sort(function (a, b) {
      return ((_catOrder[a] || {}).order || 99) - ((_catOrder[b] || {}).order || 99);
    });
    cats.forEach(function (key) {
      var meta = _catOrder[key] || categories[key] || {};
      var btn = document.createElement("button");
      btn.className = "dash-cat-btn" + (_activeCat === key ? " active" : "");
      btn.textContent = (meta.icon || "") + " " + (meta.name || key);
      btn.onclick = function () { _activeCat = key; Monitor.fetchDashboard(); };
      bar.appendChild(btn);
    });
  }

  /* ── Single instrument card ── */
  function renderCard(inst) {
    var price = inst.price;
    var change = inst.change;
    var changePct = inst.changePercent;
    var decimals = inst.decimals || 0;

    var priceStr = price != null ? price.toFixed(decimals) : "--";
    var changeStr = change != null ? (change >= 0 ? "+" : "") + change.toFixed(decimals) : "--";
    var pctStr = changePct != null ? (changePct >= 0 ? "+" : "") + changePct.toFixed(2) + "%" : "--";

    var dir = "";
    if (changePct > 0) dir = "up";
    else if (changePct < 0) dir = "down";

    var card = document.createElement("div");
    card.className = "dash-card";
    card.style.borderLeftColor = inst.color || "#888";
    card.style.cursor = "pointer";

    card.innerHTML =
      '<div class="dash-card-head">' +
        '<span class="dash-card-name">' + (inst.name || inst.id) + '</span>' +
        '<span class="dash-card-exch">' + (inst.exchange || "") + '</span>' +
      '</div>' +
      '<div class="dash-card-price ' + dir + '">' + priceStr + '</div>' +
      '<div class="dash-card-change ' + dir + '">' +
        '<span>' + changeStr + '</span>' +
        '<span class="dash-card-pct">' + pctStr + '</span>' +
      '</div>' +
      '<div class="dash-card-meta">' + (inst.unit || "") + '</div>';

    // Signal badge from backend
    if (inst.signal && inst.signal !== "neutral") {
      var sigLabels = { strong_buy: "强多", buy: "多", sell: "空", strong_sell: "强空" };
      var sigCls = inst.signal.replace("_", "-");
      var badgeEl = document.createElement("span");
      badgeEl.className = "dash-signal-badge " + sigCls;
      badgeEl.textContent = sigLabels[inst.signal] || inst.signal;
      card.querySelector(".dash-card-head").appendChild(badgeEl);
    }

    // 点击进入品种详情
    card.addEventListener("click", function () {
      if (Monitor.openDetail) Monitor.openDetail(inst);
    });

    return card;
  }

  /* ── Render grid grouped by category ── */
  function renderGrid(instruments, categories) {
    var grid = document.getElementById("dashGrid");
    if (!grid) return;
    grid.innerHTML = "";

    // group instruments
    var grouped = {};
    var count = 0;
    instruments.forEach(function (inst) {
      if (_activeCat !== "all" && inst.category !== _activeCat) return;
      var cat = inst.category || "other";
      if (!grouped[cat]) grouped[cat] = [];
      grouped[cat].push(inst);
      count++;
    });

    // sort categories
    var catKeys = Object.keys(grouped);
    catKeys.sort(function (a, b) {
      return ((_catOrder[a] || {}).order || 99) - ((_catOrder[b] || {}).order || 99);
    });

    catKeys.forEach(function (cat) {
      var meta = _catOrder[cat] || categories[cat] || {};
      // category header
      var header = document.createElement("div");
      header.className = "dash-cat-header";
      header.textContent = (meta.icon || "") + " " + (meta.name || cat);
      grid.appendChild(header);

      // cards container
      var cardsWrap = document.createElement("div");
      cardsWrap.className = "dash-cards";

      grouped[cat].forEach(function (inst) {
        cardsWrap.appendChild(renderCard(inst));
      });

      grid.appendChild(cardsWrap);
    });

    var countEl = document.getElementById("dashCount");
    if (countEl) countEl.textContent = count;
  }

  /* ── Fetch and render ── */
  Monitor.fetchDashboard = function () {
    fetch(Monitor.apiBase + "/api/instruments?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || !data.instruments) return;
        Monitor.instrumentSignals = {};
        data.instruments.forEach(function (inst) {
          if (inst && inst.id && inst.signal) {
            Monitor.instrumentSignals[inst.id] = inst.signalInfo || {
              signal: inst.signal,
              strength: inst.signalStrength,
            };
          }
        });
        buildCatBar(data.categories || {});
        renderGrid(data.instruments, data.categories || {});
      })
      .catch(function (err) {
        console.error("[dashboard]", err);
      });
  };
})();
