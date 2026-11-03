/* The Eval Index — client. Fetch data.json, render the leaderboard, wire search/filter/sort. */
(function () {
  "use strict";
  var DATA = { items: [], categories: [], count: 0, generated_at: null };
  var state = { q: "", cat: "all", sort: "momentum" };
  var $ = function (s, r) { return (r || document).querySelector(s); };
  function esc(s) { return (s == null ? "" : String(s)).replace(/[&<>"']/g, function (m) {
    return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[m]; }); }
  function fmt(n) { return n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "k" : String(n); }
  function ago(iso) {
    if (!iso) return "—";
    var d = (Date.now() - new Date(iso).getTime()) / 86400000;
    if (d < 1) return "today"; if (d < 30) return Math.round(d) + "d"; if (d < 365) return Math.round(d / 30) + "mo";
    return Math.round(d / 365) + "y";
  }

  var saved = null;
  try { saved = localStorage.getItem("ei-theme"); } catch (e) {}
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  $("#theme").addEventListener("click", function () {
    var cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", cur);
    try { localStorage.setItem("ei-theme", cur); } catch (e) {}
  });

  function countUp(el, target) { el.textContent=target.toLocaleString(); }

  function matches(it) {
    if (state.cat !== "all" && it.category !== state.cat) return false;
    if (!state.q) return true;
    return (it.full_name + " " + it.description + " " + (it.topics || []).join(" ") + " " + it.category)
      .toLowerCase().indexOf(state.q.toLowerCase()) !== -1;
  }
  function sortItems(list) {
    var s = state.sort;
    return list.slice().sort(function (a, b) {
      if (s === "stars") return b.stars - a.stars;
      if (s === "new") return new Date(b.created_at || 0) - new Date(a.created_at || 0);
      return b.momentum - a.momentum || b.stars - a.stars;
    });
  }

  function row(it, i) {
    var rk = it.rank <= 3 ? '<span class="top3">' + String(it.rank).padStart(2, "0") + "</span>" : String(it.rank).padStart(2, "0");
    var meta = ['★ ' + fmt(it.stars)];
    if (it.language) meta.push('<span class="lang">' + esc(it.language) + "</span>");
    meta.push(ago(it.pushed_at));
    if (it.license) meta.push(esc(it.license));
    return (
      '<a class="row" href="/p/' + esc(it.slug) + '/" style="transition-delay:' + (i % 14) * 30 + 'ms">' +
        '<div class="rank disp">' + rk + "</div>" +
        '<div class="r-id"><div class="r-name disp">' + esc(it.full_name) + "</div>" +
          '<div class="r-desc">' + esc(it.description || "No description.") + "</div>" +
          '<div class="r-meta">' + meta.map(function (m) { return "<span>" + m + "</span>"; }).join("") + "</div></div>" +
        '<div class="r-cat">' + esc(it.category) + "</div>" +
        '<div class="r-mom"><div class="top"><span>momentum</span><span class="score disp">' + it.momentum + "</span></div>" +
          '<div class="mbar"><i data-w="' + it.momentum + '"></i></div></div>' +
      "</a>"
    );
  }

  var shown=48;
  function render(expand) {
    if(!expand)shown=48;
    var list = sortItems(DATA.items.filter(matches)), board = $("#board");
    $("#metaline").textContent = list.length + (list.length === 1 ? " tool" : " tools") +
      (state.cat === "all" ? "" : " · " + state.cat) + (state.q ? ' · "' + state.q + '"' : "");
    if (!list.length) { board.innerHTML = '<div class="empty">No eval tools match. Try a broader search.</div>'; return; }
    board.innerHTML = list.slice(0,shown).map(row).join("") + (list.length>shown ? '<button type="button" class="fleet-load-more">Show '+Math.min(48,list.length-shown)+' more · '+Math.min(shown,list.length)+' of '+list.length+' shown</button>' : '');
    var more=board.querySelector('.fleet-load-more');
    if(more)more.addEventListener('click',function(){var first=shown;shown+=48;render(true);var next=board.querySelectorAll('a')[first];if(next)next.focus();});
    var rows = board.querySelectorAll(".row");
    requestAnimationFrame(function () {
      rows.forEach(function (r) { r.classList.add("in"); });
      board.querySelectorAll(".mbar i").forEach(function (b) { b.style.width = b.getAttribute("data-w") + "%"; });
    });
  }

  function chips() {
    var box = $("#chips"), html = ['<button class="chip active" data-cat="all">All <span class="ct">' + DATA.count + "</span></button>"];
    DATA.categories.forEach(function (c) {
      html.push('<button class="chip" data-cat="' + esc(c.name) + '">' + esc(c.name) + ' <span class="ct">' + c.count + "</span></button>");
    });
    box.innerHTML = html.join("");
    box.addEventListener("click", function (e) {
      var b = e.target.closest(".chip"); if (!b) return;
      box.querySelectorAll(".chip").forEach(function (x) { x.classList.remove("active"); });
      b.classList.add("active"); state.cat = b.getAttribute("data-cat"); render();
    });
  }

  function boot() {
    countUp($("#s-count"), DATA.count);
    countUp($("#s-cats"), DATA.categories.length);
    $("#s-top").textContent = DATA.items.length ? DATA.items[0].momentum : "—";
    if (DATA.generated_at) {
      $("#foot-updated").textContent = "Last recomputed " + new Date(DATA.generated_at).toUTCString().replace("GMT", "UTC");
    }
    chips(); render();
    var qi = $("#q"), t;
    qi.addEventListener("input", function () { clearTimeout(t); t = setTimeout(function () { state.q = qi.value.trim(); render(); }, 120); });
    $("#sort").addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b) return;
      $("#sort").querySelectorAll("button").forEach(function (x) { x.classList.remove("active"); });
      b.classList.add("active"); state.sort = b.getAttribute("data-sort"); render();
    });
  }

  fetch("/data.json?v=" + Date.now()).then(function (r) { return r.json(); }).then(function (d) { DATA = d; boot(); })
    .then(function(){if(window.dispatchEvent&&window.Event)window.dispatchEvent(new window.Event("catalog:ready"));}).catch(function () {
    if(window.dispatchEvent&&window.Event)window.dispatchEvent(new window.Event("catalog:error")); $("#metaline").textContent = "Could not load the leaderboard. Refresh to retry."; });
})();
