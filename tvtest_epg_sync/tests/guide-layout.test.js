const test = require('node:test')
const assert = require('node:assert/strict')
const { variableTimeline, pixelAt, filterServices } = require('../app/static/guide-layout.js')

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
