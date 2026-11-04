const test = require('node:test')
const assert = require('node:assert/strict')
const {
  variableTimeline, pixelAt, filterServices, matchesGenres, sanitizeFilters,
  GENRES, OTHER_GENRE,
} = require('../app/static/guide-layout.js')

const start = Date.parse('2026-08-30T04:00:00+09:00')
const end = start + 60 * 60000
const event = (fromMinute, duration) => ({
  start: new Date(start + fromMinute * 60000).toISOString(),
  end: new Date(start + (fromMinute + duration) * 60000).toISOString(),
})

test('keeps the normal scale when every event already has enough height', () => {
  const timeline = variableTimeline([{ events: [event(0, 30)] }], start, end, 2, 36)
  assert.equal(timeline.cumulativePixels[60], 120)
})

test('expands a short event to at least one readable row', () => {
  const timeline = variableTimeline([{ events: [event(10, 5)] }], start, end, 2, 36)
  assert.equal(pixelAt(timeline.cumulativePixels, 10), 20)
  assert.equal(pixelAt(timeline.cumulativePixels, 15) - pixelAt(timeline.cumulativePixels, 10), 40)
  assert.equal(timeline.cumulativePixels[60], 150)
})

test('uses a shared maximum scale instead of stacking channels separately', () => {
  const services = [
    { events: [event(10, 5)] },
    { events: [event(10, 5)] },
  ]
  const timeline = variableTimeline(services, start, end, 2, 36)
  assert.equal(timeline.cumulativePixels[60], 150)
})

test('interpolates fractional minutes on the accumulated timeline', () => {
  const timeline = variableTimeline([{ events: [event(0, 5)] }], start, end, 2, 36)
  assert.equal(pixelAt(timeline.cumulativePixels, 2.5), 20)
})

test('filters services by broadcast network without changing their order', () => {
  const services = [
    { name: '地デジ1', network_type: 'terrestrial' },
    { name: 'BS1', network_type: 'bs' },
    { name: '地デジ2', network_type: 'terrestrial' },
  ]
  assert.deepEqual(filterServices(services, 'terrestrial').map(item => item.name), ['地デジ1', '地デジ2'])
  assert.deepEqual(filterServices(services, 'all'), services)
})

test('hides one-seg, data and simulcast services unless asked for them', () => {
  const services = [
    { name: '琉球朝日放送', nid: 0x7c14, tsid: 0x7c14, sid: 0xf820, service_type: 1 },
    { name: '琉球朝日放送', nid: 0x7c14, tsid: 0x7c14, sid: 0xf821, service_type: 1, simulcast_of: 0xf820 },
    { name: 'ＮＨＫＥテレ２沖縄', nid: 0x7c11, tsid: 0x7c11, sid: 0xf809, service_type: 1 },
    { name: 'ＯＴＶワンセグ', nid: 0x7c17, tsid: 0x7c17, sid: 0xf9b8, service_type: 192 },
    { name: 'ＮＨＫ　ＢＳ (02BC)', nid: 4, tsid: 0x40f1, sid: 0x2bc, name_fallback: true },
  ]
  assert.deepEqual(
    filterServices(services, 'all').map(item => item.sid),
    [0xf820, 0xf809]
  )
  assert.equal(filterServices(services, 'all', true).length, 5)
})

test('keeps a sub channel that shares its name with the base service', () => {
  // BS日テレとBS-TBSのサブチャンネルは本局と同じ局名を名乗る。独自番組を
  // 流すものはサーバが simulcast_of を付けないので、番組表に残す。
  const services = [
    { name: 'ＢＳ日テレ', nid: 4, tsid: 0x40d0, sid: 0x8d, service_type: 1 },
    { name: 'ＢＳ日テレ', nid: 4, tsid: 0x40d0, sid: 0x8e, service_type: 1 },
    { name: 'ＢＳ日テレ', nid: 4, tsid: 0x40d0, sid: 0x8f, service_type: 1, simulcast_of: 0x8d },
  ]
  assert.deepEqual(filterServices(services, 'all').map(item => item.sid), [0x8d, 0x8e])
  assert.equal(filterServices(services, 'all', true).length, 3)
})

test('applies the broadcast network and service filters together', () => {
  const services = [
    { name: '地デジ1', network_type: 'terrestrial', service_type: 1 },
    { name: '地デジ1ワンセグ', network_type: 'terrestrial', service_type: 192 },
    { name: 'BS1', network_type: 'bs', service_type: 1 },
  ]
  assert.deepEqual(filterServices(services, 'terrestrial').map(item => item.name), ['地デジ1'])
  assert.deepEqual(
    filterServices(services, 'terrestrial', true).map(item => item.name),
    ['地デジ1', '地デジ1ワンセグ']
  )
})

test('keeps every program when no genre is chosen', () => {
  const drama = { genres: [[3, 0]] }
  assert.equal(matchesGenres(drama, []), true)
  assert.equal(matchesGenres(drama, undefined), true)
})

test('matches a program on any of its genres', () => {
  // 映画ジャンルのアニメは大分類を二つ持つ。どちらで絞っても出したい。
  const animatedFilm = { genres: [[6, 2], [7, 0]] }
  assert.equal(matchesGenres(animatedFilm, [6]), true)
  assert.equal(matchesGenres(animatedFilm, [7]), true)
  assert.equal(matchesGenres(animatedFilm, [1, 7]), true)
  assert.equal(matchesGenres(animatedFilm, [1]), false)
})

test('treats reserved genres and missing genres as other', () => {
  assert.equal(matchesGenres({ genres: [[14, 1]] }, [OTHER_GENRE]), true)
  assert.equal(matchesGenres({ genres: [] }, [OTHER_GENRE]), true)
  assert.equal(matchesGenres({}, [OTHER_GENRE]), true)
  assert.equal(matchesGenres({ genres: [] }, [3]), false)
})

test('offers one chip per genre up to the other bucket', () => {
  assert.equal(GENRES.length, OTHER_GENRE + 1)
  assert.deepEqual(GENRES.map(item => item.value), [...Array(OTHER_GENRE + 1).keys()])
  assert.ok(GENRES.every(item => item.label))
})

test('restores filters that were stored', () => {
  assert.deepEqual(
    sanitizeFilters({ network: 'bs', service: 'all', zoom: '3', genres: [7, 3] }),
    { network: 'bs', service: 'all', zoom: '3', genres: [3, 7] }
  )
})

test('falls back to the defaults when nothing was stored', () => {
  const defaults = { network: 'all', service: 'main', zoom: '2', genres: [] }
  assert.deepEqual(sanitizeFilters(null), defaults)
  assert.deepEqual(sanitizeFilters(undefined), defaults)
  assert.deepEqual(sanitizeFilters('bs'), defaults)
  assert.deepEqual(sanitizeFilters({}), defaults)
})

test('drops stored values it does not recognise', () => {
  // 古い版が書いた値や、書き換えられた値をそのまま画面に入れない。
  assert.deepEqual(
    sanitizeFilters({ network: 'cable', service: 'everything', zoom: 9, genres: [3, 99, 'ドラマ'] }),
    { network: 'all', service: 'main', zoom: '2', genres: [3] }
  )
  assert.deepEqual(sanitizeFilters({ genres: 'ドラマ' }).genres, [])
  // select の値は文字列なので、数の 3 は受け付けない。
  assert.equal(sanitizeFilters({ zoom: 3 }).zoom, '2')
})

// ---- createRefreshScheduler ----
const { createRefreshScheduler } = require('../app/static/guide-layout.js')

function fakeClock() {
  let time = 0
  let nextId = 1
  const timers = new Map()
  return {
    now: () => time,
    setTimeout: (fn, ms) => { const id = nextId++; timers.set(id, { fn, at: time + ms }); return id },
    clearTimeout: (id) => { timers.delete(id) },
    pending: () => timers.size,
    async advance(ms) {
      const until = time + ms
      for (;;) {
        let next = null
        for (const [id, t] of timers) if (t.at <= until && (!next || t.at < next[1].at)) next = [id, t]
        if (!next) break
        timers.delete(next[0])
        time = next[1].at
        next[1].fn()
        await flush()
      }
      time = until
      await flush()
    },
  }
}
const flush = () => new Promise((resolve) => setImmediate(resolve))

function deferredRun() {
  const calls = []
  const run = (immediate) => new Promise((resolve) => calls.push({ immediate, resolve }))
  return { calls, run }
}

test('collapses a burst of update notices into one refresh', async () => {
  const clock = fakeClock()
  const { calls, run } = deferredRun()
  const s = createRefreshScheduler(run, { minInterval: 30000, delay: 300, ...clock })
  for (let i = 0; i < 50; i++) s.request()
  await clock.advance(300)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].immediate, false)
})

test('does not start another refresh while one is still loading', async () => {
  const clock = fakeClock()
  const { calls, run } = deferredRun()
  const s = createRefreshScheduler(run, { minInterval: 30000, delay: 300, ...clock })
  s.request()
  await clock.advance(300)
  for (let i = 0; i < 100; i++) { s.request(); await clock.advance(1000) }
  assert.equal(calls.length, 1, 'still waiting for the first response')
  calls[0].resolve()
  await flush()
  await clock.advance(300)
  assert.equal(calls.length, 2, 'one follow-up refresh for everything that arrived meanwhile')
})

test('keeps at least minInterval between refresh starts even under constant notices', async () => {
  const clock = fakeClock()
  const starts = []
  const s = createRefreshScheduler(() => { starts.push(clock.now()); return Promise.resolve() },
    { minInterval: 30000, delay: 300, ...clock })
  for (let i = 0; i < 120; i++) { s.request(); await clock.advance(500) }
  assert.ok(starts.length >= 2, 'notices that never stop must not starve the refresh')
  for (let i = 1; i < starts.length; i++) assert.ok(starts[i] - starts[i - 1] >= 30000)
})

test('a user action loads at once and supersedes the background refresh', async () => {
  const clock = fakeClock()
  const { calls, run } = deferredRun()
  const s = createRefreshScheduler(run, { minInterval: 30000, delay: 300, ...clock })
  s.request()
  await clock.advance(300)
  s.now()
  await flush()
  assert.equal(calls.length, 2)
  assert.equal(calls[1].immediate, true)
  s.request()
  calls[0].resolve() // the superseded load finishing must not release the new one
  await flush()
  await clock.advance(60000)
  assert.equal(calls.length, 2)
  calls[1].resolve()
  await flush()
  await clock.advance(30000)
  assert.equal(calls.length, 3)
})

test('a failed refresh does not stop later ones', async () => {
  const clock = fakeClock()
  let count = 0
  const s = createRefreshScheduler(() => { count++; return Promise.reject(new Error('HTTP 502')) },
    { minInterval: 1000, delay: 0, ...clock })
  s.request()
  await clock.advance(0)
  s.request()
  await clock.advance(1000)
  assert.equal(count, 2)
})
