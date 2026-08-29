# Changelog

## 0.1.14

- Bundle an optional JK EPG custom integration and install it on add-on startup.
- Add one current/next-program sensor per channel.
- Add a read-only EPG calendar usable by Home Assistant calendar automations and notifications.

## 0.1.13

- Add aggregate and source-level EPG acquisition status.
- Add an explicit manual external-EPG refresh action with concurrency protection.
- Rename the existing button to Display refresh to distinguish the two operations.

## 0.1.12

- Add a responsive current/next program view alongside the full schedule.
- Reuse channel, favorite, genre and search preferences in the compact view.

## 0.1.11

- Add persistent favorite channels and an optional favorites-only view.
- Keep favorite channels at the left of the guide.
- Add accessible up/down channel ordering controls and persist the custom order.

## 0.1.10

- Add an accessible program-details dialog for mouse and keyboard users.
- Show channel, broadcast time, duration, genre and EPG source.

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
