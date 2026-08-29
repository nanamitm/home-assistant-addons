const $ = id => document.getElementById(id)
const dateInput=$('date'), guide=$('guide'), loading=$('loading'), status=$('status')
let schedule=null
const api = path => new URL(path, document.baseURI)
const pad=n=>String(n).padStart(2,'0')
const localDate=d=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`
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
  const value=$('genre').value, genres=new Map()
  schedule.channels.forEach(c=>c.programs.forEach(p=>{if(p.genreCode&&p.genreName)genres.set(p.genreCode,p.genreName)}))
  $('genre').innerHTML='<option value="all">全ジャンル</option>'+[...genres].sort().map(([k,v])=>`<option value="${k}">${escapeHtml(v)}</option>`).join('')
  if(genres.has(value))$('genre').value=value
}
function render(){
  const band=$('band').value, genre=$('genre').value
  const channels=schedule.channels.filter(c=>(band==='all'||(band==='bs')===c.bs)&&c.programs.some(p=>genre==='all'||p.genreCode===genre))
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
      const box=document.createElement('article');box.className=`program g${parseInt(p.genreCode||'8',16)%8}`;box.style.top=`${cumulativePixels[first]}px`;box.style.height=`${Math.max(2,cumulativePixels[last]-cumulativePixels[first]-2)}px`;box.title=`${p.genreName||''} ${p.title}`
      box.innerHTML=`<time>${pad(new Date(p.startAt).getHours())}:${pad(new Date(p.startAt).getMinutes())}–${pad(new Date(p.endAt).getHours())}:${pad(new Date(p.endAt).getMinutes())}</time><strong>${escapeHtml(p.title)}</strong>`;col.append(box)} guide.append(col)
  }
  if(!channels.length)guide.innerHTML+='<div class="message">該当する番組がありません</div>'
  const now=Date.now();if(now>=start&&now<end){const minute=Math.min(totalMinutes,Math.max(0,Math.floor((now-start)/60000)));const line=document.createElement('div');line.className='now';line.style.top=`${48+cumulativePixels[minute]}px`;guide.append(line)}
}
function escapeHtml(s){const e=document.createElement('span');e.textContent=s;return e.innerHTML}
dateInput.value=broadcastToday();$('prev').onclick=()=>shift(-1);$('next').onclick=()=>shift(1);$('today').onclick=()=>{dateInput.value=broadcastToday();load()};$('reload').onclick=load;dateInput.onchange=load;$('band').onchange=render;$('genre').onchange=render;load()
