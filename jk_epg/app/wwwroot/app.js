const $ = id => document.getElementById(id)
const dateInput=$('date'), guide=$('guide'), loading=$('loading'), status=$('status')
let schedule=null
const selectedGenres=new Set()
const genreMeta={
  '0':{name:'ニュース／報道',className:'genre-0'},
  '1':{name:'スポーツ',className:'genre-1'},
  '2':{name:'情報／ワイドショー',className:'genre-2'},
  '3':{name:'ドラマ',className:'genre-3'},
  '4':{name:'音楽',className:'genre-4'},
  '5':{name:'バラエティ',className:'genre-5'},
  '6':{name:'映画',className:'genre-6'},
  '7':{name:'アニメ／特撮',className:'genre-7'},
  '8':{name:'ドキュメンタリー／教養',className:'genre-8'},
  '9':{name:'劇場／公演',className:'genre-9'},
  'a':{name:'趣味／教育',className:'genre-a'},
  'b':{name:'福祉',className:'genre-b'},
  'f':{name:'その他',className:'genre-f'},
  unknown:{name:'ジャンル不明',className:'genre-unknown'},
}
const api = path => new URL(path, document.baseURI)
const pad=n=>String(n).padStart(2,'0')
const localDate=d=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`
const genreKey=code=>{const key=String(code||'').toLowerCase().replace('0x','');return genreMeta[key]?key:'unknown'}
function broadcastToday(){const d=new Date();if(d.getHours()<5)d.setDate(d.getDate()-1);return localDate(d)}
function shift(days){const [y,m,d]=dateInput.value.split('-').map(Number), value=new Date(y,m-1,d);value.setDate(value.getDate()+days);dateInput.value=localDate(value);load()}

async function load(){
  loading.hidden=false; guide.hidden=true; status.textContent='取得中…'
  try{
    const response=await fetch(api(`api/programs/schedule?date=${encodeURIComponent(dateInput.value)}`),{cache:'no-store'})
    if(!response.ok)throw new Error(`${response.status} ${response.statusText}`)
    schedule=await response.json(); buildGenres(); render()
    status.textContent=schedule.loaded?`更新 ${schedule.updatedAt?new Date(schedule.updatedAt).toLocaleTimeString('ja-JP'):'キャッシュ'}`:'データなし'
  }catch(error){loading.textContent=`取得失敗: ${error.message}`;status.textContent='エラー';return}
  loading.hidden=true;guide.hidden=false
}
function buildGenres(){
  const genres=new Map()
  schedule.channels.forEach(c=>c.programs.forEach(p=>{const value=p.genreCode||'__unknown__',meta=genreMeta[genreKey(p.genreCode)];genres.set(value,p.genreName||meta.name)}))
  for(const value of [...selectedGenres])if(!genres.has(value))selectedGenres.delete(value)
  const options=$('genre-filter-options');options.innerHTML=''
  for(const [value,name] of [...genres].sort((a,b)=>genreKey(a[0]).localeCompare(genreKey(b[0])))){
    const meta=genreMeta[genreKey(value)],label=document.createElement('label');label.className=`genre-filter-option ${meta.className}`
    const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.value=value;checkbox.checked=selectedGenres.has(value)
    checkbox.addEventListener('change',()=>{checkbox.checked?selectedGenres.add(value):selectedGenres.delete(value);updateGenreFilterSummary(genres);render()})
    label.innerHTML='<i></i>';label.append(checkbox,document.createTextNode(name));options.append(label)
  }
  updateGenreFilterSummary(genres)
  const keys=new Set([...genres.keys()].map(genreKey))
  $('legend-items').innerHTML=[...keys].sort().map(key=>`<span class="legend-item ${genreMeta[key].className}"><i></i>${escapeHtml(genreMeta[key].name)}</span>`).join('')
}
function updateGenreFilterSummary(genres){
  const names=[...selectedGenres].map(value=>genres.get(value)).filter(Boolean)
  $('genre-filter-summary').textContent=names.length===0?'全ジャンル':names.length===1?names[0]:`ジャンル ${names.length}件`
  $('genre-filter-clear').disabled=names.length===0
}
function render(){
  const band=$('band').value
  const channels=schedule.channels
    .filter(c=>band==='all'||(band==='bs')===c.bs)
    .map(c=>({...c,programs:selectedGenres.size===0?c.programs:c.programs.filter(p=>selectedGenres.has(p.genreCode||'__unknown__'))}))
    .filter(c=>c.programs.length>0)
  guide.style.setProperty('--count',Math.max(1,channels.length)); guide.innerHTML='<div class="corner">時刻</div>'+channels.map(c=>`<div class="channel">${escapeHtml(c.name)}</div>`).join('')
  const start=new Date(schedule.startAt).getTime(), end=new Date(schedule.endAt).getTime()
  const totalMinutes=Math.max(1,Math.round((end-start)/60000))
  const oneMinutePx=2, minimumProgramPx=36

  // jkcnsl-cacheと同じEDCB方式の可変ピクセル密度。短い番組が最低36pxに
  // なるよう該当時間帯のpx/分を増やし、その増分を以降の時刻へ積み上げる。
  const pixelsPerMinute=new Array(totalMinutes).fill(oneMinutePx)
  for(const channel of channels){
    for(const program of channel.programs){
      const programStart=Math.max(start,new Date(program.startAt).getTime())
      const programEnd=Math.min(end,new Date(program.endAt).getTime())
      const durationMinutes=Math.ceil((programEnd-programStart)/60000)
      if(durationMinutes<=0||durationMinutes*oneMinutePx>=minimumProgramPx)continue
      const needed=Math.ceil(minimumProgramPx/durationMinutes)
      const first=Math.max(0,Math.floor((programStart-start)/60000))
      const last=Math.min(totalMinutes-1,first+durationMinutes-1)
      for(let minute=first;minute<=last;minute++)pixelsPerMinute[minute]=Math.max(pixelsPerMinute[minute],needed)
    }
  }
  const cumulativePixels=new Array(totalMinutes+1).fill(0)
  for(let minute=0;minute<totalMinutes;minute++)cumulativePixels[minute+1]=cumulativePixels[minute]+pixelsPerMinute[minute]
  const bodyHeight=cumulativePixels[totalMinutes]
  guide.style.setProperty('--body-height',`${bodyHeight}px`)

  const times=document.createElement('div');times.className='times'
  for(let minute=0;minute<=totalMinutes;minute+=60){
    const tick=document.createElement('div');tick.className='time';tick.style.top=`${cumulativePixels[minute]}px`
    const t=new Date(start+minute*60000);tick.textContent=`${pad(t.getHours())}:00`;times.append(tick)
    const line=document.createElement('div');line.className='grid-line';line.style.top=`${48+cumulativePixels[minute]}px`;guide.append(line)
  }
  guide.append(times)
  for(const channel of channels){
    const col=document.createElement('div');col.className='column'
    for(const p of channel.programs){const a=Math.max(start,new Date(p.startAt).getTime()),b=Math.min(end,new Date(p.endAt).getTime());if(b<=a)continue
      const first=Math.max(0,Math.floor((a-start)/60000)),last=Math.min(totalMinutes,Math.ceil((b-start)/60000))
      const height=Math.max(2,cumulativePixels[last]-cumulativePixels[first]-2),meta=genreMeta[genreKey(p.genreCode)]
      const sizeClass=height>=52?'with-badge':height<36?'tiny':'compact'
      const box=document.createElement('article');box.className=`program ${meta.className} ${sizeClass}`;box.style.top=`${cumulativePixels[first]}px`;box.style.height=`${height}px`;box.title=`${p.genreName||meta.name}: ${p.title}`
      const badge=height>=52?`<span class="genre-badge">${escapeHtml(p.genreName||meta.name)}</span>`:''
      box.innerHTML=`<div class="program-meta"><time>${pad(new Date(p.startAt).getHours())}:${pad(new Date(p.startAt).getMinutes())}–${pad(new Date(p.endAt).getHours())}:${pad(new Date(p.endAt).getMinutes())}</time>${badge}</div><strong>${escapeHtml(p.title)}</strong>`;col.append(box)} guide.append(col)
  }
  if(!channels.length)guide.innerHTML+='<div class="message">該当する番組がありません</div>'
  const now=Date.now();if(now>=start&&now<end){const minute=Math.min(totalMinutes,Math.max(0,Math.floor((now-start)/60000)));const line=document.createElement('div');line.className='now';line.style.top=`${48+cumulativePixels[minute]}px`;guide.append(line)}
}
function escapeHtml(s){const e=document.createElement('span');e.textContent=s;return e.innerHTML}
dateInput.value=broadcastToday();$('prev').onclick=()=>shift(-1);$('next').onclick=()=>shift(1);$('today').onclick=()=>{dateInput.value=broadcastToday();load()};$('reload').onclick=load;dateInput.onchange=load;$('band').onchange=render;$('genre-filter-clear').onclick=()=>{selectedGenres.clear();buildGenres();render()};load()
