# Changelog

## 0.1.9

- Add case-insensitive program-title search with a live match count.
- Dim non-matching programs while keeping the schedule layout stable.

## 0.1.8

- Add a Current button that returns to today and scrolls to the current-time line.
- Scroll to the current time automatically when opening today's schedule.

## 0.1.7

- Dim programs outside the selected genres instead of hiding them.
- Keep the schedule geometry stable while changing genre selections.

## 0.1.6

- Persist multi-select genre filters in browser local storage.
- Remove saved genres automatically when they are no longer available.

## 0.1.5

- Add a checkbox panel for choosing which channels appear in the schedule.
- Persist channel selections in browser local storage.
- Add shortcuts for all, terrestrial, BS/CS and no channels.

## 0.1.4

- Replace the single-choice genre selector with a multi-select checkbox panel.
- Apply selected genres as an OR filter and provide a one-click reset to all genres.

## 0.1.3

- Fix the genre filter so non-matching programs are excluded from the schedule.
- Recalculate variable row heights using only the displayed genre.

## 0.1.2

- Add subtle genre-colored card backgrounds and stronger matching accent lines.
- Show textual genre badges on cards with enough room.
- Add a collapsible genre legend and compact layouts for short programs.

## 0.1.1

- Use the same variable pixel-density schedule layout as the jkcnsl-cache web client.
- Give short programs enough height to keep their time and title readable.

## 0.1.0

- Initial experimental release.
- TVer, NHK, AT-X, Open University of Japan and supported BS subchannel EPG sources.
- Ingress-compatible schedule guide and persistent SQLite cache.
