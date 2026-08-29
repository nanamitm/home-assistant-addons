(function (root, factory) {
  const api = factory()
  if (typeof module === 'object' && module.exports) module.exports = api
  else root.JkEpgUi = api
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const pad = value => String(value).padStart(2, '0')
  const localDate = date => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  const genreKey = (code, genreMeta) => {
    const key = String(code || '').toLowerCase().replace('0x', '')
    return genreMeta[key] ? key : 'unknown'
  }
  const matchesProgram = (program, genres, searchQuery) =>
    (genres.size === 0 || genres.has(program.genreCode || '__unknown__')) &&
    (!searchQuery || program.title.toLocaleLowerCase('ja').includes(searchQuery))
  const variableTimeline = (channels, start, end, oneMinutePx = 2, minimumProgramPx = 36) => {
    const totalMinutes = Math.max(1, Math.round((end - start) / 60000))
    const pixelsPerMinute = new Array(totalMinutes).fill(oneMinutePx)
    for (const channel of channels) for (const program of channel.programs) {
      const programStart = Math.max(start, new Date(program.startAt).getTime())
      const programEnd = Math.min(end, new Date(program.endAt).getTime())
      const durationMinutes = Math.ceil((programEnd - programStart) / 60000)
      if (durationMinutes <= 0 || durationMinutes * oneMinutePx >= minimumProgramPx) continue
      const needed = Math.ceil(minimumProgramPx / durationMinutes)
      const first = Math.max(0, Math.floor((programStart - start) / 60000))
      const last = Math.min(totalMinutes - 1, first + durationMinutes - 1)
      for (let minute = first; minute <= last; minute++)
        pixelsPerMinute[minute] = Math.max(pixelsPerMinute[minute], needed)
    }
    const cumulativePixels = new Array(totalMinutes + 1).fill(0)
    for (let minute = 0; minute < totalMinutes; minute++)
      cumulativePixels[minute + 1] = cumulativePixels[minute] + pixelsPerMinute[minute]
    return { totalMinutes, cumulativePixels }
  }
  return { pad, localDate, genreKey, matchesProgram, variableTimeline }
})
