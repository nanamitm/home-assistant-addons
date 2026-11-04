(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.EpgSyncGuideLayout = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function variableTimeline(services, start, end, oneMinutePx, minimumEventPx) {
    var totalMinutes = Math.max(1, Math.round((end - start) / 60000));
    var pixelsPerMinute = new Array(totalMinutes).fill(oneMinutePx);

    (services || []).forEach(function (service) {
      (service.events || []).forEach(function (event) {
        var eventStart = Math.max(start, new Date(event.start).getTime());
        var eventEnd = Math.min(end, new Date(event.end).getTime());
        var first = Math.max(0, Math.floor((eventStart - start) / 60000));
        var last = Math.min(totalMinutes, Math.ceil((eventEnd - start) / 60000));
        var duration = last - first;
        if (duration <= 0 || duration * oneMinutePx >= minimumEventPx) return;

        var needed = Math.ceil(minimumEventPx / duration);
        for (var minute = first; minute < last; minute += 1) {
          pixelsPerMinute[minute] = Math.max(pixelsPerMinute[minute], needed);
        }
      });
    });

    var cumulativePixels = new Array(totalMinutes + 1).fill(0);
    for (var minute = 0; minute < totalMinutes; minute += 1) {
      cumulativePixels[minute + 1] = cumulativePixels[minute] + pixelsPerMinute[minute];
    }
    return { totalMinutes: totalMinutes, cumulativePixels: cumulativePixels };
  }

  function pixelAt(cumulativePixels, minute) {
    var last = cumulativePixels.length - 1;
    var position = Math.max(0, Math.min(last, minute));
    var whole = Math.floor(position);
    if (whole >= last) return cumulativePixels[last];
    return cumulativePixels[whole]
      + (cumulativePixels[whole + 1] - cumulativePixels[whole]) * (position - whole);
  }

  // ARIB のジャンル大分類。12 以降は予備・拡張なので「その他」にまとめ、
  // ジャンルを持たない番組もそこへ入れる。
  var OTHER_GENRE = 12;
  var GENRES = [
    { value: 0, label: "ニュース" },
    { value: 1, label: "スポーツ" },
    { value: 2, label: "情報" },
    { value: 3, label: "ドラマ" },
    { value: 4, label: "音楽" },
    { value: 5, label: "バラエティ" },
    { value: 6, label: "映画" },
    { value: 7, label: "アニメ" },
    { value: 8, label: "ドキュメンタリー" },
    { value: 9, label: "劇場" },
    { value: 10, label: "趣味" },
    { value: 11, label: "福祉" },
    { value: OTHER_GENRE, label: "その他" }
  ];

  function matchesGenres(event, selected) {
    if (!selected || !selected.length) return true;
    var genres = (event && event.genres) || [];
    if (!genres.length) return selected.indexOf(OTHER_GENRE) >= 0;
    for (var i = 0; i < genres.length; i += 1) {
      var level1 = genres[i][0];
      if (typeof level1 !== "number") continue;
      if (level1 > OTHER_GENRE) level1 = OTHER_GENRE;
      if (selected.indexOf(level1) >= 0) return true;
    }
    return false;
  }

  var NETWORK_FILTERS = ["all", "terrestrial", "bs", "cs", "other"];
  var SERVICE_FILTERS = ["main", "all"];
  // 1分あたりの高さ。select の値と同じく文字列で持つ。
  var ZOOM_LEVELS = ["1", "2", "3"];
  var DEFAULT_FILTERS = { network: "all", service: "main", zoom: "2", genres: [] };

  function sanitizeFilters(stored) {
    // 保存された値は古い版のものかもしれないし、人が書き換えているかもしれない。
    // 知っている値だけを拾い、残りは既定に戻す。
    var result = {
      network: DEFAULT_FILTERS.network,
      service: DEFAULT_FILTERS.service,
      zoom: DEFAULT_FILTERS.zoom,
      genres: []
    };
    if (!stored || typeof stored !== "object") return result;
    if (NETWORK_FILTERS.indexOf(stored.network) >= 0) result.network = stored.network;
    if (SERVICE_FILTERS.indexOf(stored.service) >= 0) result.service = stored.service;
    if (ZOOM_LEVELS.indexOf(stored.zoom) >= 0) result.zoom = stored.zoom;
    if (Array.isArray(stored.genres)) {
      GENRES.forEach(function (genre) {
        if (stored.genres.indexOf(genre.value) >= 0) result.genres.push(genre.value);
      });
    }
    return result;
  }

  // ARIB のサービス形式。デジタルTVとデジタル音声だけを主要サービスとみなす。
  var MAIN_SERVICE_TYPES = [0x01, 0x02];

  function isMainService(service) {
    // 局名が推測のものはデータ放送などなので主要サービスにしない。
    if (service.name_fallback) return false;
    // 局名が届いていれば形式で判定する。ワンセグとデータ放送は 0xC0。
    if (typeof service.service_type === "number"
        && MAIN_SERVICE_TYPES.indexOf(service.service_type) < 0) return false;
    // 本局と同じ番組しか流さないサブチャンネルはサーバが印を付けている。
    // 独自番組を持つサブチャンネルには付かないので、局名が本局と同じでも残る。
    if (typeof service.simulcast_of === "number") return false;
    return true;
  }

  function filterServices(services, networkType, includeAllServices) {
    return (services || []).filter(function (service) {
      if (networkType && networkType !== "all" && service.network_type !== networkType) return false;
      return includeAllServices || isMainService(service);
    });
  }

  // 再取得を間引く。run() は Promise を返す取得処理。
  // - request(): 更新通知などの「そのうち取り直したい」要求。取得中なら完了後に
  //   1 回だけ、そうでなければ前回の開始から minInterval 以上空けて 1 回だけ走らせる。
  //   要求が続いても期限は先送りしないので、通知が途切れなくても定期的に更新される。
  // - now(): 日付変更などの利用者操作。待たずにすぐ走らせる(前の取得の中断は run 側)。
  function createRefreshScheduler(run, options) {
    options = options || {};
    var minInterval = options.minInterval == null ? 30000 : options.minInterval;
    var delayMin = options.delay == null ? 300 : options.delay;
    var setTimer = options.setTimeout || setTimeout;
    var clearTimer = options.clearTimeout || clearTimeout;
    var now = options.now || Date.now;
    var timer = null;
    var running = false;
    var pending = false;
    var lastStart = -Infinity;
    var generation = 0;

    function clearScheduled() {
      if (timer !== null) clearTimer(timer);
      timer = null;
    }

    function start(immediate) {
      clearScheduled();
      pending = false;
      running = true;
      lastStart = now();
      var id = ++generation;
      function finished() {
        if (id !== generation) return; // now() で置き換えられた古い取得
        running = false;
        if (pending) request();
      }
      var result;
      try {
        result = Promise.resolve(run(immediate));
      } catch (error) {
        result = Promise.reject(error);
      }
      result.then(finished, finished);
    }

    function request() {
      if (running) {
        pending = true;
        return;
      }
      if (timer !== null) return;
      var wait = Math.max(delayMin, lastStart + minInterval - now());
      timer = setTimer(function () {
        timer = null;
        start(false);
      }, wait);
    }

    return {
      request: request,
      now: function () { start(true); },
      isBusy: function () { return running || timer !== null; }
    };
  }

  return {
    createRefreshScheduler: createRefreshScheduler,
    variableTimeline: variableTimeline,
    pixelAt: pixelAt,
    filterServices: filterServices,
    GENRES: GENRES,
    OTHER_GENRE: OTHER_GENRE,
    matchesGenres: matchesGenres,
    sanitizeFilters: sanitizeFilters
  };
}));
