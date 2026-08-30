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

  return { variableTimeline: variableTimeline, pixelAt: pixelAt };
}));
