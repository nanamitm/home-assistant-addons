"use strict";

const $ = (id) => document.getElementById(id);
const settings = Object.assign({grid:"30",projection:"linear",units:"metric",labels:true,rotation:0}, JSON.parse(localStorage.getItem("xgps-settings") || "{}"));
let satellites = [], tpv = {}, rotation = Number(settings.rotation) || 0, dragging = false, previousAngle = 0;
const rawLines = [];
const systems = {0:["GPS","#2196f3"],1:["SBAS","#9c27b0"],2:["Galileo","#ff9800"],3:["BeiDou","#f44336"],4:["IMES","#795548"],5:["QZSS","#00bcd4"],6:["GLONASS","#4caf50"],7:["IRNSS","#607d8b"]};

function saveSettings(){settings.grid=$("grid").value;settings.projection=$("projection").value;settings.units=$("units").value;settings.labels=$("labels").checked;settings.rotation=rotation;localStorage.setItem("xgps-settings",JSON.stringify(settings))}
function finite(value){return typeof value === "number" && Number.isFinite(value)}
function text(value,digits=1){return finite(value)?value.toFixed(digits):"—"}
function systemFor(sat){return systems[Number(sat.gnssid)] || [sat.gnss || "Unknown","#9e9e9e"]}
function prn(sat){return sat.PRN ?? sat.prn ?? sat.svid ?? "—"}
function snrColor(ss){if(!finite(ss)||ss<12)return "#9e9e9e";if(ss<30)return "#ef5350";if(ss<36)return "#fbc02d";if(ss<42)return "#43a047";return "#00acc1"}
function svg(name,attrs={}){const el=document.createElementNS("http://www.w3.org/2000/svg",name);Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,String(v)));return el}

function drawSky(){
  const root=$("sky");root.replaceChildren();root.append(svg("circle",{cx:0,cy:0,r:100,class:"grid-line"}));
  const step=Number($("grid").value);for(let elevation=step;elevation<90;elevation+=step){let radius=100*(90-elevation)/90;if($("projection").value==="spherical")radius=100*Math.sin((90-elevation)*Math.PI/180);root.append(svg("circle",{cx:0,cy:0,r:radius,class:"grid-line"}))}
  root.append(svg("line",{x1:-100,y1:0,x2:100,y2:0,class:"axis"}),svg("line",{x1:0,y1:-100,x2:0,y2:100,class:"axis"}));
  [[0,-103,"N"],[104,2,"E"],[0,108,"S"],[-104,2,"W"]].forEach(([x,y,label])=>{const t=svg("text",{x,y,class:"axis-label","text-anchor":"middle"});t.textContent=label;root.append(t)});
  const group=svg("g",{transform:`rotate(${rotation})`});root.append(group);const visible=satellites.filter(s=>finite(s.el)&&finite(s.az)&&s.el>=0);
  if(!visible.length){const t=svg("text",{x:0,y:3,class:"empty","text-anchor":"middle"});t.textContent="No satellite data";root.append(t);return}
  visible.forEach(sat=>{let radius=100*(90-sat.el)/90;if($("projection").value==="spherical")radius=100*Math.sin((90-sat.el)*Math.PI/180);const angle=(sat.az-90)*Math.PI/180,x=radius*Math.cos(angle),y=radius*Math.sin(angle);const marker=svg("circle",{cx:x,cy:y,r:sat.used?5:4,fill:sat.used?snrColor(sat.ss):"none",stroke:snrColor(sat.ss),class:"sat"});const title=svg("title");title.textContent=`${systemFor(sat)[0]} ${prn(sat)} · El ${text(sat.el)}° · Az ${text(sat.az)}° · SNR ${text(sat.ss)}`;marker.append(title);group.append(marker);if($("labels").checked){const label=svg("text",{x:x+6,y:y+2,class:"sat-label"});label.textContent=prn(sat);group.append(label)}})
}
function drawLegend(){const present=new Set(satellites.map(s=>Number(s.gnssid)));const root=$("legend");root.replaceChildren();[...present].sort().forEach(id=>{const [name,color]=systems[id]||["Unknown","#9e9e9e"];const span=document.createElement("span"),dot=document.createElement("i");dot.style.background=color;span.append(dot,document.createTextNode(name));root.append(span)})}
function renderSatellites(){const body=$("satellites");body.replaceChildren();[...satellites].sort((a,b)=>(Number(b.used)-Number(a.used))||((b.ss||0)-(a.ss||0))).forEach(s=>{const row=document.createElement("tr");if(s.used)row.className="used";[systemFor(s)[0],prn(s),text(s.el),text(s.az),text(s.ss),s.used?"Yes":"No"].forEach(value=>{const cell=document.createElement("td");cell.textContent=value;row.append(cell)});body.append(row)});$("sat-count").textContent=`(${satellites.length})`;drawSky();drawLegend()}
function convertSpeed(ms){const units=$("units").value;if(!finite(ms))return ["—",""];if(units==="nautical")return [(ms*1.943844).toFixed(1),"kn"];if(units==="imperial")return [(ms*2.236936).toFixed(1),"mph"];return [(ms*3.6).toFixed(1),"km/h"]}
function convertAltitude(m){const units=$("units").value;if(!finite(m))return ["—",""];if(units==="imperial")return [(m*3.28084).toFixed(1),"ft"];return [m.toFixed(1),"m"]}
function renderPosition(){const root=$("position");root.replaceChildren();const altitude=tpv.altHAE??tpv.altMSL??tpv.alt,[alt,altUnit]=convertAltitude(altitude),[speed,speedUnit]=convertSpeed(tpv.speed);const rows=[["Fix",({1:"No fix",2:"2D",3:"3D"})[tpv.mode]||"—"],["Latitude",finite(tpv.lat)?`${tpv.lat.toFixed(7)}°`:"—"],["Longitude",finite(tpv.lon)?`${tpv.lon.toFixed(7)}°`:"—"],["Altitude",`${alt} ${altUnit}`.trim()],["Speed",`${speed} ${speedUnit}`.trim()],["Track",finite(tpv.track)?`${tpv.track.toFixed(1)}°`:"—"],["Time",tpv.time||"—"]];rows.forEach(([key,value])=>{const dt=document.createElement("dt"),dd=document.createElement("dd");dt.textContent=key;dd.textContent=value;root.append(dt,dd)})}
function setStatus(connected,message){const el=$("status");el.textContent=message;el.className=`status ${connected?"connected":"disconnected"}`}
function websocketUrl(){const base=window.location.href.endsWith("/")?window.location.href:`${window.location.href}/`;const url=new URL("ws",base);url.protocol=url.protocol==="https:"?"wss:":"ws:";return url}
function connect(){const ws=new WebSocket(websocketUrl());ws.onopen=()=>setStatus(false,"Waiting for gpsd…");ws.onmessage=event=>{const msg=JSON.parse(event.data);if(msg.type==="snapshot"){satellites=msg.satellites||[];tpv=msg.tpv||{};setStatus(msg.connected,msg.status);$("raw-card").hidden=!msg.rawEnabled;(msg.raw||[]).forEach(addRaw);renderSatellites();renderPosition()}else if(msg.type==="status"){setStatus(msg.connected,msg.status)}else if(msg.type==="sky"){satellites=msg.satellites||[];renderSatellites()}else if(msg.type==="tpv"){tpv=msg.tpv||{};renderPosition()}else if(msg.type==="raw")addRaw(msg.line)};ws.onclose=()=>{setStatus(false,"Web UI disconnected — retrying…");setTimeout(connect,2000)}}
function addRaw(line){rawLines.push(line);if(rawLines.length>500)rawLines.shift();$("raw").textContent=rawLines.join("\n");$("raw").scrollTop=$("raw").scrollHeight}

["grid","projection","units","labels"].forEach(id=>{if(id==="labels")$(id).checked=settings.labels;else $(id).value=settings[id];$(id).addEventListener("change",()=>{saveSettings();drawSky();renderPosition()})});
$("reset").addEventListener("click",()=>{rotation=0;saveSettings();drawSky()});
$("sky").addEventListener("pointerdown",event=>{dragging=true;$("sky").setPointerCapture(event.pointerId);const box=$("sky").getBoundingClientRect();previousAngle=Math.atan2(event.clientY-(box.top+box.height/2),event.clientX-(box.left+box.width/2))*180/Math.PI});
$("sky").addEventListener("pointermove",event=>{if(!dragging)return;const box=$("sky").getBoundingClientRect(),angle=Math.atan2(event.clientY-(box.top+box.height/2),event.clientX-(box.left+box.width/2))*180/Math.PI;rotation+=angle-previousAngle;previousAngle=angle;drawSky()});
$("sky").addEventListener("pointerup",()=>{dragging=false;saveSettings()});
renderPosition();drawSky();connect();
