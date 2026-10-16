'use strict';
const $=id=>document.getElementById(id), NS='http://www.w3.org/2000/svg';
const names={provisional:'通过当前质量检查',review_required:'待人工复核',rejected:'精定位前拒绝',diagnostic_only:'证据不完整'};
let data,shown=100,weekly=[];
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function svg(tag,attrs){const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);return n}
function initBatchQC(){const windows=Array.isArray(data.latest_windows)?data.latest_windows:[];const section=$('batch-qc');section.hidden=!windows.length;if(!windows.length)return;
 $('qc-count').textContent=`${windows.length} 个窗口 · 展开查看`;
 let loaded=false;section.ontoggle=()=>{$('qc-count').textContent=`${windows.length} 个窗口 · ${section.open?'收起':'展开查看'}`;if(!section.open||loaded)return;loaded=true;const illustrated=new Set();
 for(const w of windows){const article=node('article',undefined,'qc-window');article.append(node('h3',`T${w.period_s} s · ${String(w.window_start_utc||'时间未提供').replace('T',' ').replace('Z',' UTC')}`));
 const count=value=>Number.isFinite(value)?value:'未提供';article.append(node('p',`${w.status==='complete'?'完成检查':w.status==='incomplete'?'未通过当前检查':w.status||'状态未提供'} · 读入台站：${count(w.station_count)} · 可评分台站：${count(w.scoring_station_count)}`,'qc-status'));
 if(w.reason)article.append(node('p',w.reason,'qc-reason'));
 const src=w.overview;if(!illustrated.has(w.period_s)&&typeof src==='string'&&(/^quality\/[A-Za-z0-9_.\/-]+\.webp$/.test(src)||/^figures\/[A-Za-z0-9_.\/-]+$/.test(src))&&!src.includes('..')){illustrated.add(w.period_s);const figure=node('figure'),a=node('a'),im=node('img');a.href=src;a.target='_blank';a.rel='noopener';im.src=src;im.loading='lazy';im.alt=`T${w.period_s} s 本批代表性波形与包络检查图`;im.onerror=()=>{im.hidden=true;figure.append(node('p','图件加载失败，请稍后重试。','image-error'));};a.append(im);figure.append(node('figcaption',`T${w.period_s} s 代表性波形与包络 · 点击图片查看大图`),a);article.append(figure)}$('qc-windows').append(article)}
 }}
function show(r){$('detail-title').textContent=`${r.origin_time_utc.replace('T',' ').replace('Z',' UTC')} · T${r.period_s} s`;
 $('detail-text').textContent=`${names[r.status]||r.status} · ${r.location_stage==='refined'?'精定位':'粗定位'}\n位置：${r.latitude.toFixed(2)}°, ${r.longitude.toFixed(2)}°；叠加分数：${r.score.toFixed(2)}；台站：${r.station_count}；有效拾取：${r.valid_pick_count}\n分析窗口：${r.window_start_utc} — ${r.window_end_utc}\n${r.reason||'通过当前自动质量检查，仍需人工确认。'}\n记录：${r.id}`;
 $('detail-images').replaceChildren();if(!r.figures?.length)$('detail-images').append(node('p','本条记录的图件不完整，暂不能作为已验证结果。'));
 for(const src of r.figures||[]){if(!/^figures\/[A-Za-z0-9_.\/-]+$/.test(src)||src.includes('..'))continue;const figure=node('figure'),caption=src.includes('location')?'定位与源时叠加诊断图':'台站波形与包络图';const a=node('a');a.href=src;a.target='_blank';a.rel='noopener';const im=node('img');im.src=src;im.alt=caption+' · '+r.candidate_id;im.loading='lazy';im.onerror=()=>{im.hidden=true;figure.append(node('p','图件加载失败，请稍后重试。','image-error'));};a.append(im);figure.append(node('figcaption',caption+' · 点击图片查看大图'),a);$('detail-images').append(figure)}$('detail').showModal()}
function matches(r){return($('period').value==='all'||r.period_s===Number($('period').value))&&($('quality').value==='all'||r.status===$('quality').value)}
function render(){const records=data.records.filter(matches);$('points').replaceChildren();
 for(const r of [...records].reverse()){if(!Number.isFinite(r.longitude)||!Number.isFinite(r.latitude))continue;const c=svg('circle',{cx:(r.longitude+180)/360*1000,cy:(90-r.latitude)/180*500,r:4,tabindex:0,role:'button','aria-label':r.origin_time_utc+' T'+r.period_s,'class':'point '+r.status+(r.batch===data.latest_batch?' latest':'')});const title=svg('title',{});title.textContent=r.origin_time_utc+' · T'+r.period_s+' · '+names[r.status];c.append(title);c.onclick=()=>show(r);c.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show(r)}};$('points').append(c)}
 $('map-count').textContent=`${records.length} 条记录（未去重）`;
 const reference=data.mode==='replay'?new Date(data.list_reference_time):new Date();const cutoff=reference.getTime()-data.list_days*864e5;
 $('list-reference').textContent=data.mode==='replay'?' 回放参考时间：'+reference.toISOString().replace('T',' ').replace('.000Z',' UTC')+'。':'';
 weekly=records.filter(r=>new Date(r.origin_time_utc).getTime()>=cutoff&&new Date(r.origin_time_utc)<=reference).sort((a,b)=>b.origin_time_utc.localeCompare(a.origin_time_utc));
 $('list-count').textContent=weekly.length+' 条';renderList()}
function renderList(){$('records').replaceChildren();for(const r of weekly.slice(0,shown)){const b=node('button',undefined,'record');b.onclick=()=>show(r);const t=node('div');t.append(node('strong',r.origin_time_utc.slice(0,10)),node('small',r.origin_time_utc.slice(11,19)+' UTC'));const pos=node('div');pos.append(node('strong',`${r.latitude.toFixed(2)}°, ${r.longitude.toFixed(2)}°`),node('small',`${r.location_stage==='refined'?'精定位':'粗定位'} · ${r.station_count} 台站`));b.append(t,pos,node('span',names[r.status]||r.status,'badge'),node('span',`T${r.period_s} s →`));$('records').append(b)}if(!weekly.length)$('records').append(node('p','最近一周没有符合筛选条件的记录。请同时查看上方运行状态。','empty'));$('more').hidden=shown>=weekly.length}
async function init(){try{const response=await fetch('data.json',{cache:'no-store'});if(!response.ok)throw Error('HTTP '+response.status);data=await response.json();
 const running=data.latest_status==='running',stamp=data.last_run_at||data.current_run_started_at;
 const age=stamp?(Date.now()-new Date(stamp))/36e5:Infinity;const stale=age>data.stale_after_hours;
 const timeLabel=value=>value?.replace('T',' ').replace('Z',' UTC');
 const qualityMessage=data.latest_status==='incomplete'&&Array.isArray(data.latest_windows)&&data.latest_windows.some(w=>w.reason)?'当前批次质量检查未通过':'数据或处理不完整';
 $('status').textContent=data.mode==='replay'?'历史波形回放预览 · 不属于当前实时检测':(running?`正在运行：${timeLabel(data.current_run_started_at)||'当前批次'}${data.last_run_at?' · 上次完成：'+timeLabel(data.last_run_at):' · 首次结果生成中'}${stale?' · 更新已延迟':''}`:(data.last_run_at?`最近运行：${timeLabel(data.last_run_at)} · ${data.latest_status==='complete'?'完成':qualityMessage}${stale?' · 更新已延迟':''}`:'尚未完成首次实时运行'));$('status').classList.toggle('warning',data.mode!=='replay'&&(stale||(!running&&data.latest_status!=='complete')));
 initBatchQC();
 $('build-time').textContent='页面生成：'+data.generated_at;
 for(let lon=-150;lon<180;lon+=30)$('grid').append(svg('line',{x1:(lon+180)/360*1000,x2:(lon+180)/360*1000,y1:0,y2:500}));for(let lat=-60;lat<90;lat+=30)$('grid').append(svg('line',{x1:0,x2:1000,y1:(90-lat)/180*500,y2:(90-lat)/180*500}));
 try{const coast=await(await fetch('coast.json')).json();for(const points of coast){const d=points.map((p,i)=>(i?'L':'M')+((p[0]+180)/360*1000).toFixed(2)+' '+((90-p[1])/180*500).toFixed(2)).join(' ');$('coast').append(svg('path',{d}))}}catch(e){console.warn('Coastline unavailable',e)}
 render();$('period').onchange=$('quality').onchange=()=>{shown=100;render()};$('blink').onchange=()=>document.body.classList.toggle('no-blink',!$('blink').checked);$('more').onclick=()=>{shown+=100;renderList()};
 }catch(e){$('status').textContent='记录暂时无法读取，请稍后刷新。'+e.message;$('status').classList.add('warning')}}
$('close').onclick=()=>$('detail').close();$('detail').onclick=e=>{if(e.target===$('detail'))$('detail').close()};init();
