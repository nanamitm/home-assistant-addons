const test = require('node:test')
const assert = require('node:assert/strict')
const { genreKey, matchesProgram, variableTimeline } = require('../app/wwwroot/ui-core.js')

test('genre filtering and title search are combined', () => {
  const program = { title: 'ニュース速報', genreCode: '0' }
  assert.equal(matchesProgram(program, new Set(['0']), 'ニュース'), true)
  assert.equal(matchesProgram(program, new Set(['1']), 'ニュース'), false)
  assert.equal(matchesProgram(program, new Set(), 'ドラマ'), false)
})

test('unknown genre codes use the fallback', () => {
  assert.equal(genreKey('ff', { unknown: {} }), 'unknown')
})

test('short programs expand the shared timeline', () => {
  const start = Date.parse('2026-01-01T05:00:00+09:00')
  const end = start + 60 * 60000
  const channels = [{ programs: [{
    startAt: new Date(start).toISOString(),
    endAt: new Date(start + 5 * 60000).toISOString(),
  }] }]
  const timeline = variableTimeline(channels, start, end)
  assert.equal(timeline.cumulativePixels[5], 40)
  assert.equal(timeline.cumulativePixels[60], 150)
})
