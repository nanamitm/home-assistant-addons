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
  const start=new Date(schedule.startAt), end=new Date(schedule.endAt)
  const times=document.createElement('div');times.className='times'
  for(let i=0;i<24;i++){const t=new Date(start.getTime()+i*3600000);times.innerHTML+=`<div class="time">${pad(t.getHours())}:00</div>`} guide.append(times)
  for(const channel of channels){
    const col=document.createElement('div');col.className='column'
    for(const p of channel.programs){const a=Math.max(start,new Date(p.startAt)),b=Math.min(end,new Date(p.endAt));if(b<=a)continue
      const box=document.createElement('article');box.className=`program g${parseInt(p.genreCode||'8',16)%8}`;box.style.top=`${(a-start)/30000}px`;box.style.height=`${Math.max(18,(b-a)/30000-2)}px`;box.title=`${p.genreName||''} ${p.title}`
      box.innerHTML=`<time>${pad(new Date(p.startAt).getHours())}:${pad(new Date(p.startAt).getMinutes())}–${pad(new Date(p.endAt).getHours())}:${pad(new Date(p.endAt).getMinutes())}</time><strong>${escapeHtml(p.title)}</strong>`;col.append(box)} guide.append(col)
  }
  if(!channels.length)guide.innerHTML+='<div class="message">該当する番組がありません</div>'
  const now=new Date();if(now>=start&&now<end){const line=document.createElement('div');line.className='now';line.style.top=`${48+(now-start)/30000}px`;guide.append(line)}
}
function escapeHtml(s){const e=document.createElement('span');e.textContent=s;return e.innerHTML}
dateInput.value=broadcastToday();$('prev').onclick=()=>shift(-1);$('next').onclick=()=>shift(1);$('today').onclick=()=>{dateInput.value=broadcastToday();load()};$('reload').onclick=load;dateInput.onchange=load;$('band').onchange=render;$('genre').onchange=render;load()
