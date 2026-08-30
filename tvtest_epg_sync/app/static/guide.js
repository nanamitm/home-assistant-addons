(function () {
  "use strict";

  var base = window.EPGSYNC_BASE || "";
  var dateInput = document.getElementById("guide-date");
  var networkFilter = document.getElementById("network-filter");
  var serviceFilter = document.getElementById("service-filter");
  var genreChips = document.getElementById("genre-chips");
  var genreAll = document.getElementById("genre-all");
  var selectedGenres = [];
  var viewport = document.getElementById("program-viewport");
  var canvas = document.getElementById("program-canvas");
  var headers = document.getElementById("channel-headers");
  var timeAxis = document.getElementById("time-axis");
  var grid = document.getElementById("guide-grid");
  var message = document.getElementById("guide-message");
  var connection = document.getElementById("connection");
  var summary = document.getElementById("guide-summary");
  var dialog = document.getElementById("event-dialog");
  var detail = document.getElementById("event-detail");
  var refreshTimer = null;
  var lastGuide = null;
  var lastTimeline = null;
  var minuteHeight = 2;
  var columnWidth = 190;
  var minimumEventHeight = 36;

  function api(path) { return base + path; }
  function pad(value) { return ("000" + Number(value).toString(16).toUpperCase()).slice(-4); }
  function serviceId(service) { return pad(service.nid) + "/" + pad(service.tsid) + "/" + pad(service.sid); }
  function localDate(date) {
    var year = date.getFullYear();
    var month = String(date.getMonth() + 1).padStart(2, "0");
    var day = String(date.getDate()).padStart(2, "0");
    return year + "-" + month + "-" + day;
  }
  function formatTime(value) {
    return new Intl.DateTimeFormat("ja-JP", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
  }
  function node(tag, className, text) {
    var element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  // 絞り込みはブラウザごとに覚えておく。番組表の中身ではないので、サーバには置かない。
  var FILTER_STORAGE_KEY = "epgsync.guide-filters";

  function loadFilters() {
    var stored = null;
    try {
      stored = JSON.parse(window.localStorage.getItem(FILTER_STORAGE_KEY));
    } catch (error) {
      // プライベートウィンドウなど、読めない環境では既定のまま始める。
    }
    return window.EpgSyncGuideLayout.sanitizeFilters(stored);
  }

  function saveFilters() {
    try {
      window.localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify({
        network: networkFilter.value,
        service: serviceFilter.value,
        genres: selectedGenres
      }));
    } catch (error) {
      // 保存できなくても表示には影響しない。
    }
  }

  function applyStoredFilters() {
    var filters = loadFilters();
    networkFilter.value = filters.network;
    serviceFilter.value = filters.service;
    selectedGenres = filters.genres;
    syncGenreChips();
  }

  function buildGenreChips() {
    window.EpgSyncGuideLayout.GENRES.forEach(function (genre) {
      var chip = node("button", "genre-chip genre-" + genre.value, genre.label);
      chip.type = "button";
      chip.setAttribute("aria-pressed", "false");
      chip.addEventListener("click", function () {
        var at = selectedGenres.indexOf(genre.value);
        if (at < 0) selectedGenres.push(genre.value); else selectedGenres.splice(at, 1);
        syncGenreChips();
        saveFilters();
        if (lastGuide) renderGuide(lastGuide);
      });
      genreChips.appendChild(chip);
    });
  }

  function syncGenreChips() {
    genreAll.classList.toggle("active", selectedGenres.length === 0);
    genreAll.setAttribute("aria-pressed", selectedGenres.length === 0 ? "true" : "false");
    Array.prototype.forEach.call(genreChips.children, function (chip, index) {
      var on = selectedGenres.indexOf(window.EpgSyncGuideLayout.GENRES[index].value) >= 0;
      chip.classList.toggle("active", on);
      chip.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function setView(name) {
    document.querySelectorAll(".tab").forEach(function (tab) {
      var selected = tab.dataset.view === name;
      tab.classList.toggle("active", selected);
      tab.setAttribute("aria-selected", selected ? "true" : "false");
    });
    document.querySelectorAll(".view").forEach(function (view) {
      view.classList.toggle("active", view.id === name + "-view");
    });
    if (name === "status") loadStatus();
  }

  function showMessage(text) {
    message.textContent = text;
    message.hidden = false;
    grid.hidden = true;
  }

  function loadGuide(keepPosition) {
    var oldLeft = viewport.scrollLeft;
    var oldTop = viewport.scrollTop;
    connection.textContent = "番組表を更新しています…";
    fetch(api("/api/guide?date=" + encodeURIComponent(dateInput.value)), { headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (data) {
        lastGuide = data;
        renderGuide(data);
        if (keepPosition) {
          viewport.scrollLeft = oldLeft;
          viewport.scrollTop = oldTop;
        }
        connection.textContent = "自動更新中 / 最終取得 " + new Date().toLocaleTimeString("ja-JP");
      })
      .catch(function (error) {
        connection.textContent = "番組表を取得できません";
        showMessage("番組表の取得に失敗しました: " + error.message);
      });
  }

  function renderGuide(data) {
    headers.replaceChildren();
    timeAxis.replaceChildren();
    canvas.replaceChildren();

    var allServices = data.services || [];
    if (!allServices.length) {
      lastTimeline = null;
      showMessage("まだEPGを受信していません。TVTestからEPGが届くとここに表示されます。");
      summary.textContent = "0サービス";
      return;
    }

    var services = window.EpgSyncGuideLayout.filterServices(
      allServices, networkFilter.value, serviceFilter.value === "all"
    );
    if (!services.length) {
      lastTimeline = null;
      showMessage("この条件で表示できるサービスがありません。");
      summary.textContent = "0サービス（全" + allServices.length + "）";
      return;
    }

    grid.hidden = false;
    message.hidden = true;
    var first = new Date(data.from);
    var last = new Date(data.to);
    var timeline = window.EpgSyncGuideLayout.variableTimeline(
      services, first.getTime(), last.getTime(), minuteHeight, minimumEventHeight
    );
    var totalMinutes = timeline.totalMinutes;
    var cumulativePixels = timeline.cumulativePixels;
    lastTimeline = timeline;
    var canvasWidth = services.length * columnWidth;
    var canvasHeight = cumulativePixels[totalMinutes];
    headers.style.width = canvasWidth + "px";
    timeAxis.style.height = canvasHeight + "px";
    canvas.style.width = canvasWidth + "px";
    canvas.style.height = canvasHeight + "px";

    for (var minute = 0; minute <= totalMinutes; minute += 60) {
      var labelTime = new Date(first.getTime() + minute * 60000);
      var label = node("div", "time-label", formatTime(labelTime));
      label.style.top = cumulativePixels[minute] + "px";
      timeAxis.appendChild(label);
    }

    for (var gridMinute = 0; gridMinute <= totalMinutes; gridMinute += 30) {
      var gridLine = node("div", "time-grid-line" + (gridMinute % 60 === 0 ? " hour" : ""));
      gridLine.style.top = cumulativePixels[gridMinute] + "px";
      gridLine.style.width = canvasWidth + "px";
      canvas.appendChild(gridLine);
    }

    var eventTotal = 0;
    var genreTotal = 0;
    services.forEach(function (service, index) {
      var header = node("div", "channel-header");
      if (service.logo) {
        var logo = node("img", "channel-logo");
        logo.src = api(service.logo);
        // 局名がすぐ隣にあるので、読み上げでは飾りとして扱う。
        logo.alt = "";
        logo.loading = "lazy";
        logo.addEventListener("error", function () { logo.remove(); });
        header.appendChild(logo);
      }
      var text = node("div", "channel-text");
      text.appendChild(node("div", "channel-name", service.name || serviceId(service)));
      text.appendChild(node("div", "channel-id", serviceId(service)));
      header.appendChild(text);
      headers.appendChild(header);

      var column = node("div", "service-column");
      column.style.left = index * columnWidth + "px";
      column.style.width = columnWidth + "px";
      canvas.appendChild(column);

      if (service.parse_error) {
        column.appendChild(node("div", "parse-error", "解析できません: " + service.parse_error));
        return;
      }

      (service.events || []).forEach(function (event) {
        eventTotal += 1;
        var start = new Date(event.start);
        var end = new Date(event.end);
        var startMinute = Math.max(0, (start - first) / 60000);
        var endMinute = Math.min(totalMinutes, (end - first) / 60000);
        var top = window.EpgSyncGuideLayout.pixelAt(cumulativePixels, startMinute);
        var bottom = window.EpgSyncGuideLayout.pixelAt(cumulativePixels, endMinute);
        if (bottom <= top) return;
        var genre = event.genres && event.genres.length ? event.genres[0][0] : null;
        var card = node("button", "event-card genre-" + (genre === null ? "none" : genre));
        card.type = "button";
        // 選んだジャンル以外は沈めるだけにして、前後の番組も見えるようにする。
        if (window.EpgSyncGuideLayout.matchesGenres(event, selectedGenres)) genreTotal += 1;
        else card.classList.add("dimmed");
        card.style.left = "2px";
        card.style.top = top + "px";
        card.style.width = columnWidth - 4 + "px";
        card.style.height = Math.max(2, bottom - top - 2) + "px";
        card.appendChild(node("div", "event-time", formatTime(event.start)));
        card.appendChild(node("div", "event-title", event.title || "（番組名なし）"));
        if (bottom - top > 66 && event.text) card.appendChild(node("div", "event-text", event.text));
        card.addEventListener("click", function () { loadEvent(service, event.event_id); });
        column.appendChild(card);
      });
    });

    var now = new Date();
    if (now >= first && now < last) {
      var line = node("div", "now-line");
      line.style.top = window.EpgSyncGuideLayout.pixelAt(
        cumulativePixels, (now - first) / 60000
      ) + "px";
      line.style.width = canvasWidth + "px";
      canvas.appendChild(line);
    }
    summary.textContent = services.length + "サービス / "
      + (selectedGenres.length ? genreTotal + " / " : "") + eventTotal + "番組"
      + (services.length === allServices.length ? "" : "（全" + allServices.length + "サービス）");
  }

  function loadEvent(service, eventId) {
    detail.replaceChildren(node("p", "", "詳細を読み込んでいます…"));
    if (dialog.showModal) dialog.showModal(); else dialog.setAttribute("open", "");
    fetch(api("/api/guide/event/" + service.nid + "/" + service.tsid + "/" + service.sid + "/" + eventId))
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (payload) { renderEventDetail(service, payload.event); })
      .catch(function (error) { detail.replaceChildren(node("p", "", "詳細を取得できません: " + error.message)); });
  }

  function renderEventDetail(service, event) {
    detail.replaceChildren();
    detail.appendChild(node("h2", "detail-title", event.title || "（番組名なし）"));
    detail.appendChild(node("p", "detail-meta", service.name + " / " + formatTime(event.start) + "–" + formatTime(event.end)));
    if (event.text) detail.appendChild(node("p", "detail-section", event.text));
    if (event.extended_text && event.extended_text.length) {
      var list = node("dl", "detail-section");
      event.extended_text.forEach(function (item) {
        list.appendChild(node("dt", "", item.description || "詳細"));
        list.appendChild(node("dd", "", item.text));
      });
      detail.appendChild(list);
    }
    detail.appendChild(node("p", "detail-meta", "NID/TSID/SID: " + serviceId(service) + " / Event ID: " + pad(event.event_id)));
  }

  function loadStatus() {
    fetch(api("/api/services"), { headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(renderStatus)
      .catch(function (error) {
        document.getElementById("status-list").replaceChildren(node("div", "empty", "同期状態を取得できません: " + error.message));
      });
  }

  function renderStatus(data) {
    var services = data.services || [];
    var events = services.reduce(function (sum, item) { return sum + item.event_count; }, 0);
    var size = services.reduce(function (sum, item) { return sum + item.size; }, 0);
    var cards = document.getElementById("status-cards");
    cards.replaceChildren();
    [[services.length, "サービス"], [events, "番組"], [(size / 1024 / 1024).toFixed(1) + " MB", "保管サイズ"],
      [data.summary ? data.summary.subscribers : 0, "接続中TVTest"]].forEach(function (value) {
      var card = node("div", "status-card");
      card.appendChild(node("div", "status-value", String(value[0])));
      card.appendChild(node("div", "status-label", value[1]));
      cards.appendChild(card);
    });

    var target = document.getElementById("status-list");
    if (!services.length) {
      target.replaceChildren(node("div", "empty", "まだEPGを受信していません。"));
      return;
    }
    var table = node("table");
    var head = node("thead");
    var headRow = node("tr");
    ["NID/TSID/SID", "番組数", "サイズ", "最終更新", "更新元"].forEach(function (text) { headRow.appendChild(node("th", "", text)); });
    head.appendChild(headRow); table.appendChild(head);
    var body = node("tbody");
    services.forEach(function (service) {
      var row = node("tr");
      row.appendChild(node("td", "mono", serviceId(service)));
      row.appendChild(node("td", "num", String(service.event_count)));
      row.appendChild(node("td", "num", Math.round(service.size / 1024) + " KB"));
      row.appendChild(node("td", "", service.updated_at));
      row.appendChild(node("td", "", service.source || "-"));
      body.appendChild(row);
    });
    table.appendChild(body); target.replaceChildren(table);
  }

  function changeDay(offset) {
    var date = new Date(dateInput.value + "T12:00:00");
    date.setDate(date.getDate() + offset);
    dateInput.value = localDate(date);
    loadGuide(false);
  }

  function scrollToNow() {
    if (!lastGuide || !lastTimeline) return;
    var first = new Date(lastGuide.from);
    var last = new Date(lastGuide.to);
    var now = new Date();
    if (now < first || now >= last) {
      dateInput.value = localDate(now);
      loadGuide(false);
      return;
    }
    viewport.scrollTop = Math.max(0, window.EpgSyncGuideLayout.pixelAt(
      lastTimeline.cumulativePixels, (now - first) / 60000
    ) - viewport.clientHeight / 3);
  }

  document.querySelectorAll(".tab").forEach(function (tab) {
    tab.addEventListener("click", function () { setView(tab.dataset.view); });
  });
  document.getElementById("prev-day").addEventListener("click", function () { changeDay(-1); });
  document.getElementById("next-day").addEventListener("click", function () { changeDay(1); });
  document.getElementById("today").addEventListener("click", function () { dateInput.value = localDate(new Date()); loadGuide(false); });
  document.getElementById("now").addEventListener("click", scrollToNow);
  dateInput.addEventListener("change", function () { loadGuide(false); });
  document.getElementById("zoom").addEventListener("change", function (event) {
    minuteHeight = Number(event.target.value);
    document.documentElement.style.setProperty("--minute-height", minuteHeight + "px");
    if (lastGuide) renderGuide(lastGuide);
  });
  [networkFilter, serviceFilter].forEach(function (filter) {
    filter.addEventListener("change", function () {
      viewport.scrollLeft = 0;
      saveFilters();
      if (lastGuide) renderGuide(lastGuide);
    });
  });
  viewport.addEventListener("scroll", function () {
    headers.style.transform = "translateX(" + (-viewport.scrollLeft) + "px)";
    timeAxis.style.transform = "translateY(" + (-viewport.scrollTop) + "px)";
  });

  buildGenreChips();
  genreAll.addEventListener("click", function () {
    if (!selectedGenres.length) return;
    selectedGenres = [];
    syncGenreChips();
    saveFilters();
    if (lastGuide) renderGuide(lastGuide);
  });
  applyStoredFilters();
  dateInput.value = localDate(new Date());
  columnWidth = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--column-width")) || 190;
  loadGuide(false);
  loadStatus();

  if (window.EventSource) {
    var source = new EventSource(api("/api/events?ui=1"));
    source.onopen = function () { connection.textContent = "自動更新中"; };
    source.onerror = function () { connection.textContent = "更新通知へ再接続しています…"; };
    source.onmessage = function () {
      clearTimeout(refreshTimer);
      refreshTimer = setTimeout(function () { loadGuide(true); loadStatus(); }, 300);
    };
  }
  setInterval(function () { loadGuide(true); }, 60000);
}());
