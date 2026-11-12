const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {projects: [], project: null, artifact: null, versions: [], favorite: false, groups: [], group: null, settings: false, detail: null, tab: 'files'};
// One stroke-based icon family; SVGs inherit the theme's text color.
const iconPaths = {
 chevron:'<path d="m9 5 7 7-7 7"/>', plus:'<path d="M12 5v14M5 12h14"/>',
 group:'<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',
 folder:'<path d="M3 7V5h6l2 2h10v13H3Z"/>',
 image:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 7"/>',
 video:'<rect x="3" y="5" width="13" height="14" rx="3"/><path d="m16 10 5-3v10l-5-3"/>',
 settings:'<path d="m10 3-.6 2.2-2 .9-2-.8-2 3.4 1.5 1.7v2.4l-1.5 1.7 2 3.4 2-.8 2 .9L10 21h4l.6-2.2 2-.9 2 .8 2-3.4-1.5-1.7v-2.4l1.5-1.7-2-3.4-2 .8-2-.9L14 3Z"/><circle cx="12" cy="12" r="3"/>',
 sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
 moon:'<path d="M20 14A8 8 0 0 1 10 4a8 8 0 1 0 10 10Z"/>',
 monitor:'<rect x="3" y="3" width="18" height="13" rx="2"/><path d="M12 16v5M8 21h8"/>',
 search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
 help:'<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.2 2.4c-.7.3-.7 1.1-.7 1.6M12 17h.01"/>'
};
function icon(name){return `<svg class="icon icon-${name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${iconPaths[name]||iconPaths.image}</svg>`;}
function themeSwitch(id){return `<div id="${id}" class="theme-switch" role="group" aria-label="${tr('Оформление')}">${[['light','sun','Светлая тема'],['system','monitor','Системная тема'],['dark','moon','Тёмная тема']].map(([value,glyph,label])=>`<button type="button" data-theme-choice="${value}" aria-pressed="${theme===value}" title="${tr(label)}" aria-label="${tr(label)}">${icon(glyph)}<span>${tr(label)}</span></button>`).join('')}</div>`;}
function artifactDescription(item,parent){return item?.description?.trim()||parent?.description?.trim()||tr('Описание не задано');}
function versionType(v){const file=outputs(v).find(f=>mediaKind(f)!=='other');return file&&mediaKind(file)==='video'?'video':'image';}
let toastTimer, formAction;
const artifactSelections=JSON.parse(localStorage.getItem('vault-artifact-selections')||'{}');
function toast(message) { $('#toast').textContent = message; $('#toast').classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 4500); }
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'Content-Type': 'application/json', ...options.headers}});
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Не удалось выполнить запрос');
  return body;
}
const post = (path, data, method = 'POST') => api(path, {method, body: JSON.stringify(data)});
const project = () => state.projects.find(p => p.id === state.project);
const artifact = () => project()?.artifacts.find(a => a.id === state.artifact);
const fileURL = (id, path, download = false) => `/api/versions/${encodeURIComponent(id)}/file?path=${encodeURIComponent(path)}${download ? '&download=true' : ''}`;
const size = n => n >= 1024**3 ? `${(n/1024**3).toFixed(2)} ГБ` : n >= 1024**2 ? `${(n/1024**2).toFixed(1)} МБ` : n >= 1024 ? `${(n/1024).toFixed(1)} КБ` : `${n} Б`;
const date = v => new Intl.DateTimeFormat(language, {day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'}).format(new Date(v));
const outputs = v => v.manifest.files.filter(f => f.role === 'output');
const mediaKind = f => /\.(png|jpe?g|webp|gif)$/i.test(f.path) ? 'image' : /\.(mp4|webm|mov|m4v)$/i.test(f.path) ? 'video' : 'other';
function media(v, f, controls = true) {
  const url = esc(fileURL(v.id, f.path)), name = esc(f.name || f.path);
  if (mediaKind(f) === 'video') return `<video src="${url}" ${controls ? 'controls' : 'muted'} preload="metadata" playsinline aria-label="${name}"></video>`;
  if (mediaKind(f) === 'image') return `<img src="${url}" alt="${name}" loading="lazy">`;
  return `<a class="button secondary" href="${esc(fileURL(v.id, f.path, true))}">Скачать ${name} ↓</a>`;
}
function persistSelection() { if(state.project&&state.artifact){artifactSelections[state.project]=state.artifact;localStorage.setItem('vault-artifact-selections',JSON.stringify(artifactSelections));} if(expanded!==null)localStorage.setItem('vault-tree',JSON.stringify(expanded));localStorage.setItem('comfy-vault-selection', JSON.stringify({project: state.project, artifact: state.artifact, group: state.group})); }
let expanded = JSON.parse(localStorage.getItem('vault-tree') || 'null');
async function loadLibrary() {
  try {
    const [data,settings]=await Promise.all([api('/api/library'),api('/api/settings')]);state.projects=data.projects;state.groups=data.groups;
    $('#repository-location').textContent=settings.repository;
    if(expanded===null){expanded={};const g=state.groups.find(g=>g.is_default);if(g)expanded[g.id]=true;}
    if(!state.groups.some(g=>g.id===state.group))state.group=state.groups.find(g=>g.is_default)?.id||state.groups[0]?.id||null;
    if(state.project&&!project())state.project=null;
    if(project())state.group=project().group_id;
    if(!artifact())state.artifact=project()?.artifacts.find(a=>a.id===artifactSelections[state.project])?.id||project()?.artifacts[0]?.id||null;
    renderLibrary();await loadVersions();
  }catch(error){toast(error.message);}
}
function controls(kind,id){return `<div class="entity-actions"><button class="button" data-edit="${kind}">${tr('Изменить')}</button>${kind!=='group'?`<button class="button" data-move="${kind}">${tr('Перенести')}</button>`:''}<button class="button danger" data-delete="${kind==='group'?'groups':kind==='project'?'projects':'artifacts'}" data-id="${esc(id)}">${tr('Удалить')}</button></div>`;}
function renderLibrary(){
  persistSelection();const p=project(),a=artifact(),g=state.groups.find(g=>g.id===state.group);if(!a||state.settings)$('#version-count').textContent='';
  $('#projects').innerHTML=state.groups.map(group=>`<div class="tree-group"><div class="tree-row"><button class="tree-toggle" aria-label="${tr('Развернуть или свернуть группу')}" data-toggle="${group.id}" aria-expanded="${!!expanded[group.id]}">${icon('chevron')}</button><button class="tree-label ${state.group===group.id&&!p?'active':''}" data-group="${group.id}">${icon('group')}<span>${esc(group.name)}</span></button><button class="tree-add" data-new-project="${group.id}" aria-label="${tr('Новый проект')}">${icon('plus')}</button></div>${expanded[group.id]?state.projects.filter(p=>p.group_id===group.id).map(p=>`<div class="tree-project"><div class="tree-row"><button class="tree-toggle" aria-label="${tr('Развернуть или свернуть проект')}" data-toggle="${p.id}" aria-expanded="${!!expanded[p.id]}">${icon('chevron')}</button><button class="tree-label ${state.project===p.id?'active':''}" data-project="${p.id}">${icon('folder')}<span>${esc(p.name)}</span></button><button class="tree-add" data-new-artifact="${p.id}" aria-label="${tr('Новый артефакт')}">${icon('plus')}</button></div>${expanded[p.id]?p.artifacts.map(a=>`<button class="tree-artifact ${state.artifact===a.id?'active':''}" data-artifact="${a.id}" data-owner="${p.id}">${icon(a.media_type==='video'?'video':'image')}<span>${esc(a.name)}</span></button>`).join(''):''}</div>`).join(''):''}</div>`).join('')||`<p>${tr('Нет групп')}</p>`;
  $('#breadcrumb-project').textContent=[g?.name,p?.name,a?.name].filter(Boolean).join(' > ')||tr('Библиотека');
  $('.artifact-heading').classList.toggle('hidden',!p||state.settings);$('#add-artifact').disabled=!p;
  $('#toolbar').classList.toggle('hidden',!a||state.settings);$('#artifacts').classList.toggle('hidden',!p||state.settings);
  $('#project-header').innerHTML='';$('#artifact-header').innerHTML='';
  if(state.settings){renderSettings();return;}
  if(!p&&g){
    $('#project-header').innerHTML=`<div><h1 data-user>${esc(g.name)}</h1>${controls('group',g.id)}</div><button class="button primary" data-new-project="${g.id}">+ ${tr('Новый проект')}</button>`;
    $('#versions').innerHTML=state.projects.filter(p=>p.group_id===g.id).map(p=>`<button class="project-summary" data-project="${p.id}"><h2>${esc(p.name)}</h2><p>${esc(p.description)}</p><span>${p.artifacts.length} ${tr('Артефакты')}</span></button>`).join('')||`<div class="empty">${tr('Нет проектов')}<p>${tr('Создайте проект или импортируйте репозиторий в настройках.')}</p><button class="button" data-settings>${tr('Настройки')}</button></div>`;return;
  }
  if(!p)return;
  $('#project-header').innerHTML=`<div><h1 data-user>${esc(p.name)}</h1><p class="project-description">${esc(p.description)}</p>${controls('project',p.id)}</div>`;
  $('#artifacts').innerHTML=`<details class="artifact-picker"><summary><strong>${esc(a?.name||tr('Выберите артефакт'))}</strong><em title="${esc(artifactDescription(a,p))}">${esc(artifactDescription(a,p))}</em><span class="picker-chevron">${icon('chevron')}</span></summary><div class="artifact-options">${p.artifacts.map(item=>{const v=item.latest,f=v&&outputs(v).find(f=>mediaKind(f)!=='other');return `<button class="artifact-option ${item.id===state.artifact?'active':''}" data-artifact="${item.id}" aria-pressed="${item.id===state.artifact}"><span class="artifact-thumb">${f?media(v,f,false):icon(item.media_type==='video'?'video':'image')}</span><span>${tr(item.media_type==='video'?'Видео':'Изображение')}</span><strong>${esc(item.name)}</strong><span class="full-description" title="${esc(artifactDescription(item,p))}">${esc(artifactDescription(item,p))}</span></button>`;}).join('')||tr('Нет артефактов')}</div></details>`;
  $('#artifact-header').innerHTML=a?`${controls('artifact',a.id)}<div class="history-heading"><h3>${tr('История версий')}</h3><button class="button" id="refresh">↻ ${tr('Обновить')}</button></div>`:'';
  $('#refresh')?.addEventListener('click',loadLibrary);
}
function visibleVersions(){const query=$('#search').value.trim().toLowerCase();let items=state.versions.filter(v=>(!state.favorite||v.favorite)&&(!query||JSON.stringify([v.number,v.note,v.metadata,v.manifest.models]).toLowerCase().includes(query)));return $('#sort').value==='asc'?[...items].reverse():items;}
let mediaItems=[],mediaIndex=0;
function openMedia(id){mediaItems=visibleVersions().flatMap(v=>outputs(v).filter(f=>mediaKind(f)!=='other').map(f=>({v,f})));mediaIndex=mediaItems.findIndex(x=>x.v.id===id);if(mediaIndex<0)return;renderMedia();$('#media-dialog').showModal();}
function renderMedia(){const {v,f}=mediaItems[mediaIndex];$('#media-title').textContent=`${tr('Версия')} ${String(v.number).padStart(3,'0')} · ${mediaIndex+1}/${mediaItems.length}`;$('#media-stage').innerHTML=media(v,f,true);$('#media-prev').disabled=mediaIndex===0;$('#media-next').disabled=mediaIndex===mediaItems.length-1;$('#media-original').href=fileURL(v.id,f.path);}
function moveMedia(delta){if(mediaIndex+delta<0||mediaIndex+delta>=mediaItems.length)return;mediaIndex+=delta;renderMedia();}
async function renderSettings(){
  $('#artifacts').innerHTML='';$('#versions').innerHTML='';const cfg=await api('/api/settings');if(!state.settings)return;
  $('#project-header').innerHTML=`<div class="settings-panel"><h1>${tr('Настройки')}</h1><div class="setting-row"><span>${tr('Оформление')}</span>${themeSwitch('settings-theme')}</div><div class="font-size-setting"><label for="settings-font-size">${tr('Размер шрифта')}</label><div class="font-size-controls"><input id="settings-font-size" type="range" min="12" max="22" step="1" value="${fontSize}" aria-describedby="font-size-hint"><output id="font-size-value" for="settings-font-size">${fontSize} px</output><button id="font-size-reset" class="button" type="button">${tr('Сбросить')}</button></div><p id="font-size-hint" class="muted small">${tr('Изменяет размер всего текста приложения. Выбор сохраняется в этом браузере.')}</p></div><label>${tr('Язык')}<select id="settings-language">${$('#language').innerHTML}</select></label><h2>${tr('Репозиторий')}</h2><p>${tr('Каталог репозитория')}</p><input id="repository-path" value="${esc(cfg.repository)}"><button class="button" data-browse="repository-path">${tr('Выбрать каталог')}</button><button class="button" id="switch-repository">${tr('Открыть репозиторий')}</button><p class="muted">${tr('Открывает существующий или создаёт пустой репозиторий. Текущие данные остаются в прежнем каталоге.')}</p><h2>${tr('Резервная копия')}</h2><input id="backup-path" placeholder="${esc(cfg.browse_root)}/ComfyUI_Vault_backup"><button class="button" data-browse="backup-path">${tr('Выбрать каталог')}</button><button class="button" id="backup-repository">${tr('Экспортировать')}</button><p>${tr('Укажите новый или пустой каталог назначения.')}</p><h2>${tr('Импорт репозитория')}</h2><input id="import-path"><button class="button" data-browse="import-path">${tr('Выбрать каталог')}</button><button class="button danger" id="import-repository">${tr('Импортировать')}</button><p>${tr('Импорт заменит все текущие группы, проекты, артефакты и версии. Сначала создайте резервную копию.')}</p></div>`;
$('#settings-font-size').addEventListener('input',e=>setFontSize(e.target.value));
$('#font-size-reset').onclick=()=>setFontSize(16);
$('#settings-language').value=language;
$('#settings-language').onchange=e=>setLanguage(e.target.value);
  $('#switch-repository').onclick=async()=>{try{await post('/api/settings/repository',{path:$('#repository-path').value});state.project=null;state.artifact=null;state.group=null;expanded=null;await loadLibrary();toast(tr('Сохранено'));}catch(e){toast(e.message);}};
  $('#backup-repository').onclick=async()=>{try{await post('/api/repository/backup',{path:$('#backup-path').value});toast(tr('Резервная копия сохранена'));}catch(e){toast(e.message);}};
  $('#import-repository').onclick=async()=>{if(!await confirmAction(tr('Импорт репозитория'),tr('Импорт заменит все текущие группы, проекты, артефакты и версии. Сначала создайте резервную копию.'),tr('Импортировать')))return;try{await post('/api/repository/import',{path:$('#import-path').value});state.project=null;state.artifact=null;state.group=null;expanded=null;await loadLibrary();toast(tr('Сохранено'));}catch(e){toast(e.message);}};
}
async function loadVersions() {
  if (!state.artifact) {state.versions = []; renderVersions(); return;}
  const artifactId = state.artifact;
  const body = await api(`/api/artifacts/${artifactId}/versions`);
  if (state.artifact !== artifactId) return;
  state.versions = body.versions;
  renderVersions();
}
function renderVersions() {
  if(state.settings || (!state.project && state.group)) return;
  const p = project(), a = artifact();
  $('#version-count').textContent = a ? `${state.versions.length} версий · ${state.versions.reduce((n,v) => n + outputs(v).length, 0)} результатов` : '';
  if (!p) {$('#versions').innerHTML = `<div class="empty welcome"><div class="empty-symbol">◈</div><span class="eyebrow">ВАША БИБЛИОТЕКА ГЕНЕРАЦИЙ</span><h2>Сохраните путь к результату</h2><p>Референсы, workflow и параметры каждого запуска — в одной версии. Создайте первый проект или подключите ноду: она создаст его автоматически.</p><button class="button primary" id="first-project">+ Создать проект</button> <button class="button secondary" id="first-setup">Подключить ComfyUI ↗</button></div>`; $('#first-project').onclick=()=>openForm('project'); $('#first-setup').onclick=()=>$('#help-dialog').showModal(); return;}
  if (!a) {$('#versions').innerHTML = `<div class="empty"><div class="empty-symbol">▱</div><h2>Что будем создавать?</h2><p>Артефакт — отдельная работа внутри проекта: обложка, персонаж, сцена или видеоролик. У каждой работы будет своя история.</p><button class="button primary" id="first-artifact">+ Создать артефакт</button></div>`; $('#first-artifact').onclick=()=>openForm('artifact'); return;}
  if (!state.versions.length) {$('#versions').innerHTML = `<div class="empty"><div class="empty-symbol">↶</div><h2>Здесь начнётся история</h2><p>${tr("Укажите эти названия в Archive Images или Archive Files:")} <b data-user>${esc(p.name)} / ${esc(a.name)}</b>. ${tr("После генерации здесь появится первая версия.")}</p><button class="button secondary" id="empty-setup">Как подключить ноду ↗</button></div>`; $('#empty-setup').onclick=()=>$('#help-dialog').showModal(); return;}
  const items = visibleVersions();
  $('#versions').innerHTML = items.map(v => {
    const result = outputs(v), m = v.metadata, sampler = m.samplers[0]?.parameters || {}, model = v.manifest.models?.find(x => ['checkpoints','diffusion_models','unet'].includes(x.category)) || v.manifest.models?.[0];
    const params = [['SEED', sampler.seed ?? sampler.noise_seed], ['STEPS', sampler.steps], ['CFG', sampler.cfg], ['SAMPLER', sampler.sampler_name], ['SCHEDULER', sampler.scheduler], ['DENOISE', sampler.denoise]];
    const prompt = m.prompts[0]?.text;
    return `<article class="version-card" data-open="${esc(v.id)}" tabindex="0"><div class="version-visual" data-media="${esc(v.id)}" tabindex="0" role="button" aria-label="Открыть версию ${v.number}">${result[0] ? media(v,result[0],false) : '<span class="muted">Нет превью</span>'}<span class="version-badge" title="${tr(versionType(v)==='video'?'Видео':'Изображение')}">${icon(versionType(v))}V${String(v.number).padStart(3,'0')}</span>${result.length > 1 ? `<span class="output-count">${result.length} результатов</span>` : ''}</div><div class="version-info"><div class="version-top"><h3>Версия ${String(v.number).padStart(3,'0')}</h3><time datetime="${esc(v.created_at)}">${esc(date(v.created_at))}</time><button class="star ${v.favorite ? 'selected':''}" data-star="${esc(v.id)}" aria-label="${v.favorite?'Убрать из избранного':'В избранное'}">${v.favorite?'★':'☆'}</button></div><div class="param-grid">${params.map(([label,value])=>`<div><span class="param-label">${label}</span><span class="param-value">${esc(value ?? '—')}</span></div>`).join('')}</div>${m.samplers.length > 1 ? `<span class="subtle">${m.samplers.length} ноды с параметрами · показана первая</span>`:''}<div><span class="param-label">ПРОМПТ${m.prompts.length>1?` · ${m.prompts.length}`:''}</span><p class="prompt-text">${esc(prompt || tr('Нет распознанного текстового промпта; проверьте workflow.'))}</p></div><div class="chips">${model ? `<span class="chip" title="${esc(model.comfy_path || model.name)}">${esc(model.name)}</span>` : '<span class="chip">Модель не распознана</span>'}${m.loras.map(l=>`<span class="chip purple">${esc(l.parameters.lora_name || l.title)} · ${esc(l.parameters.strength_model ?? l.parameters.strength ?? '—')}</span>`).join('')}</div>${v.note?`<p class="version-note">${esc(v.note)}</p>`:''}<div class="version-bottom"><span class="${v.manifest.warnings?.length ? 'warning-badge' : 'muted'}">${v.manifest.warnings?.length ? '△ Есть замечания к полноте архива' : `${v.manifest.files.length} файлов · workflow сохранён`}</span><button class="text-button" data-delete="versions" data-id="${esc(v.id)}">Удалить</button><button class="text-button" data-open="${esc(v.id)}">Открыть версию ↗</button></div></div></article>`;
  }).join('') || '<div class="empty"><h3>Подходящих версий нет</h3><p>Измените запрос или выключите фильтр избранного.</p></div>';
}
function openForm(action){
  formAction=action;const edit=action.startsWith('edit-'),kind=action.replace('edit-',''),value=kind==='group'?state.groups.find(g=>g.id===state.group):kind==='project'?project():artifact();
  $('#type-label').classList.toggle('hidden',kind!=='artifact');$('#entity-type').value=edit?value.media_type||'photo':'photo';
  $('#form-title').textContent=tr(edit?'Изменить':kind==='group'?'Новая группа':kind==='project'?'Новый проект':'Новый артефакт');
  $('#name-label').classList.remove('hidden');$('#entity-name').required=true;$('#entity-name').value=edit?value.name:'';
  $('#entity-description').closest('label').classList.toggle('hidden',kind==='group');$('#entity-description').value=edit?value.description||'':'';
  $('#form-hint').textContent=kind==='project'?tr('Название проекта должно быть уникальным во всём репозитории: нода ComfyUI находит проект по названию.'):'';
  $('#form-dialog').showModal();$('#entity-name').focus();
}
$('#entity-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=$('#entity-form button[type=submit]');button.disabled=true;
  try{const kind=formAction.replace('edit-',''),edit=formAction.startsWith('edit-'),table=kind==='group'?'groups':kind==='project'?'projects':'artifacts';let body={name:$('#entity-name').value.trim()};if(kind!=='group')body.description=$('#entity-description').value;if(kind==='artifact')body.media_type=$('#entity-type').value;
    if(!edit&&kind==='project')body.group_id=state.group;if(!edit&&kind==='artifact')body.project_id=state.project;
    const id=kind==='group'?state.group:kind==='project'?state.project:state.artifact;
    const result=await post(`/api/${table}${edit?'/'+id:''}`,body,edit?'PATCH':'POST');
    if(!edit){if(kind==='group'){state.group=result.id;state.project=null;state.artifact=null;expanded[result.id]=true;}else if(kind==='project'){state.project=result.id;state.artifact=null;expanded[state.group]=true;}else state.artifact=result.id;}
    $('#form-dialog').close();await loadLibrary();toast(tr('Сохранено'));
  }catch(e){toast(e.message);}finally{button.disabled=false;}
});
function confirmAction(title,message,accept=tr('Удалить')){return new Promise(resolve=>{const d=$('#confirm-dialog');$('#confirm-title').textContent=title;$('#confirm-message').textContent=message;$('#confirm-delete').textContent=accept;d.onclose=()=>resolve(d.returnValue==='accept');$('#confirm-cancel').onclick=()=>d.close('cancel');$('#confirm-delete').onclick=()=>d.close('accept');d.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();d.close('cancel');}};d.returnValue='cancel';d.showModal();$('#confirm-cancel').focus();});}
async function removeEntity(table,id){const warning={groups:'Группа, все входящие проекты, артефакты, версии и их файлы будут удалены безвозвратно.',projects:'Проект, все его артефакты, версии и их файлы будут удалены безвозвратно.',artifacts:'Артефакт, все его версии и их файлы будут удалены безвозвратно.',versions:'Версия и все её файлы будут удалены безвозвратно.'}[table];const label=table==='groups'?state.groups.find(x=>x.id===id)?.name:table==='projects'?state.projects.find(x=>x.id===id)?.name:table==='artifacts'?artifact()?.name:tr('Версия')+' '+state.versions.find(x=>x.id===id)?.number;if(!await confirmAction(tr('Подтвердите удаление')+' — '+(label||''),tr(warning)))return;await api(`/api/${table}/${id}`,{method:'DELETE'});if(table==='groups'&&state.group===id){state.group=null;state.project=null;state.artifact=null;}if(table==='projects'&&state.project===id){state.project=null;state.artifact=null;}if(table==='artifacts'&&state.artifact===id)state.artifact=null;$('#detail-dialog').close();await loadLibrary();}
async function moveEntity(kind){const isProject=kind==='project',items=isProject?state.groups:state.projects,id=isProject?state.project:state.artifact,parent=isProject?project().group_id:state.project;
  const d=document.createElement('dialog');d.className='form-dialog';d.innerHTML=`<h2>${tr('Перенести')}</h2><select aria-label="${tr('Назначение')}">${items.filter(x=>x.id!==parent).map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('')}</select><div class="dialog-actions"><button class="button" data-cancel>${tr('Отмена')}</button><button class="button primary" data-accept ${items.filter(x=>x.id!==parent).length?'':'disabled'}>${tr('Перенести')}</button></div>`;document.body.append(d);d.onclose=()=>d.remove();d.querySelector('[data-cancel]').onclick=()=>d.close();d.querySelector('[data-accept]').onclick=async()=>{try{const target=d.querySelector('select').value;await post(`/api/${isProject?'projects':'artifacts'}/${id}`,{[isProject?'group_id':'project_id']:target},'PATCH');if(isProject)state.group=target;else state.project=target;d.close();await loadLibrary();}catch(e){toast(e.message);}};d.showModal();}
let directoryTarget;
async function browseDirectory(path){try{const data=await api('/api/directories?path='+encodeURIComponent(path));$('#directory-path').value=data.path;$('#directory-list').innerHTML=`<button class="button" data-directory="${esc(data.parent)}">↑ ..</button>`+data.directories.map(p=>`<button class="directory-item" data-directory="${esc(p)}">▱ ${esc(p.split('/').pop())}</button>`).join('');}catch(e){toast(e.message);}}
function parameterGroup(title, value) { return `<div class="parameter-group"><h3>${esc(title)}</h3><dl class="parameter-list">${Object.entries(value).map(([key,val])=>`<dt>${esc(key)}</dt><dd>${esc(typeof val==='object'?JSON.stringify(val):val)}</dd>`).join('')}</dl></div>`; }
function renderDetail() {
  const v=state.detail, m=v.metadata;
  $('#detail-content').innerHTML=`<div class="detail-top"><div class="dialog-heading"><h2>Версия ${String(v.number).padStart(3,'0')}</h2><button class="icon-button" data-close="detail-dialog" aria-label="Закрыть">×</button></div><div class="detail-subtitle">${esc(v.project_name)} / ${esc(v.artifact_name)} <span>· ${esc(date(v.created_at))}</span></div></div><div class="detail-body"><div class="detail-previews">${outputs(v).map(f=>media(v,f)).join('')}</div>${v.manifest.warnings?.length?`<ul class="warning-list">${v.manifest.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul>`:''}<nav class="detail-tabs" aria-label="Данные версии">${[['files','Файлы'],['parameters','Параметры'],['models','Модели и пути'],['environment','Окружение'],['workflow','Workflow']].map(([key,title])=>`<button class="detail-tab ${state.tab===key?'active':''}" data-tab="${key}">${title}</button>`).join('')}</nav><div id="detail-panel"></div><div class="note-area"><label>ЗАМЕТКА К ВЕРСИИ<textarea class="note-input" id="version-note" maxlength="20000" placeholder="Что изменили и как оцениваете результат">${esc(v.note)}</textarea></label><button id="save-note" class="button secondary compact">Сохранить заметку</button></div></div>`;
  renderDetailPanel();
  $('#save-note').onclick=async()=>{try{const note=$('#version-note').value;await post(`/api/versions/${v.id}`,{note},'PATCH');v.note=note;const card=state.versions.find(x=>x.id===v.id);if(card)card.note=note;renderVersions();toast('Заметка сохранена');}catch(error){toast(error.message);}};
}
function renderDetailPanel(){
  const v=state.detail,m=v.metadata; let content='';
  document.querySelectorAll('.detail-tab').forEach(el=>el.classList.toggle('active',el.dataset.tab===state.tab));
  if(state.tab==='files'){
    content=`<p class="muted small">Скачайте нужные файлы. Для входных данных указан путь назначения относительно ComfyUI.</p><table class="file-table"><thead><tr><th>ФАЙЛ / ПУТЬ</th><th>ТИП</th><th>РАЗМЕР</th><th></th></tr></thead><tbody>${v.files.map(f=>`<tr><td>${esc(f.name||f.path)}<small>${esc(f.comfy_path||f.path)}</small></td><td class="muted">${{input:'Референс',output:'Результат',metadata:'Описание'}[f.role]||esc(f.role)}</td><td class="muted">${size(f.size||0)}</td><td><a class="download" href="${esc(fileURL(v.id,f.path,true))}">Скачать ↓</a></td></tr>`).join('')}</tbody></table>`;
  }else if(state.tab==='parameters'){
    content=m.samplers.map(s=>parameterGroup(`${s.title} · нода #${s.node_id}`,s.parameters)).join('');
    content+=m.dimensions.map(s=>parameterGroup(`${s.title} · нода #${s.node_id}`,s.parameters)).join('');
    content+=m.prompts.map(p=>`<div class="section-block"><h3>${esc(p.title)} <span class="muted small">#${esc(p.node_id)} · ${esc(p.field)}</span></h3><pre>${esc(p.text)}</pre></div>`).join('');
    content+=m.loras.map(l=>parameterGroup(`LoRA · ${l.title} #${l.node_id}`,l.parameters)).join('');
    if(Object.keys(m.explicit_values||{}).length)content+=parameterGroup('Значения, явно переданные в архивирующую ноду',m.explicit_values);
    if(m.unresolved.length)content+=`<div class="section-block"><h3>Вычисляемые значения, которые не удалось определить</h3><p class="muted small">Сохранена связь в графе. Это не фактическое значение; при необходимости передайте его через Capture Value.</p><pre>${esc(JSON.stringify(m.unresolved,null,2))}</pre></div>`;
    if(!content)content='<p class="muted">Параметры не распознаны. Откройте полный workflow.</p>';
  }else if(state.tab==='models'){
    const models=v.manifest.models||[];
    content=`<p class="muted small">Веса не включены в архив. Пути ниже — ожидаемое расположение при стандартной установке ComfyUI. При extra_model_paths можно использовать свои каталоги.</p><div class="section-block"><pre>${esc('ComfyUI/\n'+models.map(x=>'  '+(x.comfy_path||`[путь не определён] ${x.name}`)).join('\n'))}</pre></div>${models.map(x=>parameterGroup(x.name,{path:x.comfy_path||'Не определён — проверьте loader-ноду',category:x.category||'unknown',node:x.node_id,sha256:x.sha256||'Не вычислен',...(x.size?{size:size(x.size)}:{})})).join('')}${!models.length?'<p class="warning-badge">Модели не распознаны автоматически; проверьте ноды загрузки в workflow.</p>':''}<a class="block-link" href="${esc(fileURL(v.id,'manifest.json',true))}">Скачать манифест ↓</a>`;
  }else if(state.tab==='environment'){
    content='<div class="section-block"><h3>ComfyUI, custom nodes и зависимости</h3><p class="muted small">Снимок версий окружения помогает повторить запуск. Побитовое совпадение на другом оборудовании не гарантируется.</p><pre id="environment-json">Загрузка…</pre></div>';
  }else{
    content=`<div class="section-block"><h3>Исходный workflow</h3><p class="muted small">Визуальный граф сохраняется без изменений. Фактические значения запуска находятся в API-графе. При ручном открытии проверьте seed и переключите randomize/increment в fixed.</p>${v.files.some(f=>f.path==='workflow.json')?`<a class="button secondary" href="${esc(fileURL(v.id,'workflow.json',true))}">Workflow для ComfyUI ↓</a>`:''} <a class="button secondary" href="${esc(fileURL(v.id,'prompt.json',true))}">API-граф запуска ↓</a><pre id="workflow-json">Загрузка…</pre></div>`;
  }
  $('#detail-panel').innerHTML=content;
  if(state.tab==='environment'||state.tab==='workflow'){
    const tab=state.tab,target=tab==='environment'?'environment-json':'workflow-json';
    fetch(fileURL(v.id,tab==='environment'?'environment.json':'prompt.json')).then(r=>r.text()).then(text=>{if(state.detail?.id===v.id&&state.tab===tab&&document.getElementById(target))document.getElementById(target).textContent=text;}).catch(error=>toast(error.message));
  }
}
async function openVersion(id){try{state.detail=await api(`/api/versions/${id}`);state.tab='files';renderDetail();$('#detail-dialog').showModal();}catch(error){toast(error.message);}}
document.addEventListener('click',async event=>{
  const target=event.target;
  const themeButton=target.closest('[data-theme-choice]');if(themeButton){setTheme(themeButton.dataset.themeChoice);return;}
  try{
    const close=target.closest('[data-close]');if(close){document.getElementById(close.dataset.close).close();return;}
    const toggle=target.closest('[data-toggle]');if(toggle){expanded[toggle.dataset.toggle]=!expanded[toggle.dataset.toggle];localStorage.setItem('vault-tree',JSON.stringify(expanded));renderLibrary();return;}
    const group=target.closest('[data-group]');if(group){state.settings=false;state.group=group.dataset.group;state.project=null;state.artifact=null;await loadLibrary();return;}
    const np=target.closest('[data-new-project]');if(np){state.settings=false;state.group=np.dataset.newProject;openForm('project');return;}
    const na=target.closest('[data-new-artifact]');if(na){state.settings=false;state.project=na.dataset.newArtifact;state.group=project().group_id;openForm('artifact');return;}
    const p=target.closest('[data-project]');if(p){state.settings=false;state.project=p.dataset.project;state.artifact=null;state.group=project().group_id;$('#search').value='';await loadLibrary();return;}
    const a=target.closest('[data-artifact]');if(a){state.settings=false;if(a.dataset.owner)state.project=a.dataset.owner;state.group=project().group_id;state.artifact=a.dataset.artifact;$('#search').value='';renderLibrary();await loadVersions();return;}
    const edit=target.closest('[data-edit]');if(edit){openForm('edit-'+edit.dataset.edit);return;}
    const del=target.closest('[data-delete]');if(del){await removeEntity(del.dataset.delete,del.dataset.id);return;}
    const move=target.closest('[data-move]');if(move){await moveEntity(move.dataset.move);return;}
    const star=target.closest('[data-star]');if(star){const v=state.versions.find(v=>v.id===star.dataset.star);await post(`/api/versions/${v.id}`,{favorite:!v.favorite},'PATCH');v.favorite=!v.favorite;renderVersions();return;}
    const mediaTarget=target.closest('[data-media]');if(mediaTarget){openMedia(mediaTarget.dataset.media);return;}
    const open=target.closest('[data-open]');if(open&&!target.closest('a')){await openVersion(open.dataset.open);return;}
    const tab=target.closest('[data-tab]');if(tab){state.tab=tab.dataset.tab;renderDetailPanel();return;}
    if(target.closest('[data-settings]')){$('#settings').click();return;}
    const browse=target.closest('[data-browse]');if(browse){directoryTarget=browse.dataset.browse;const cfg=await api('/api/settings');await browseDirectory(cfg.browse_root);$('#directory-dialog').showModal();return;}
    const dir=target.closest('[data-directory]');if(dir)await browseDirectory(dir.dataset.directory);
  }catch(e){toast(e.message);}
});
document.addEventListener('keydown',e=>{if($('#media-dialog').open){if(e.key==='ArrowLeft')moveMedia(-1);if(e.key==='ArrowRight')moveMedia(1);return;}if(e.target.matches('[data-open],[data-media]')&&(e.key==='Enter'||e.key===' ')){e.preventDefault();e.target.click();}});
$('#media-dialog').addEventListener('close',()=>{$('#media-stage').innerHTML='';});
$('#media-prev').onclick=()=>moveMedia(-1);$('#media-next').onclick=()=>moveMedia(1);$('#media-size').onclick=()=>$('#media-stage').classList.toggle('actual-size');
$('#directory-go').onclick=()=>browseDirectory($('#directory-path').value);$('#directory-select').onclick=()=>{document.getElementById(directoryTarget).value=$('#directory-path').value;$('#directory-dialog').close();};
$('#add-group').onclick=()=>openForm('group');$('#add-artifact').onclick=()=>openForm('artifact');
$('#settings').onclick=()=>{state.settings=true;renderLibrary();};
$('#setup').onclick=()=>$('#help-dialog').showModal();
$('#search').addEventListener('input',renderVersions);$('#sort').addEventListener('change',renderVersions);
$('#favorites').onclick=()=>{state.favorite=!state.favorite;$('#favorites').setAttribute('aria-pressed',state.favorite);renderVersions();};
$('#language').onchange=e=>setLanguage(e.target.value);
try{const saved=JSON.parse(localStorage.getItem('comfy-vault-selection')||'{}');Object.assign(state,{project:saved.project,artifact:saved.artifact,group:saved.group});}catch{}
document.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML=icon(el.dataset.icon));
$('#theme').outerHTML=themeSwitch('theme');
setTheme(theme);$('#language').value=language;
loadLibrary().then(async()=>{const requested=new URLSearchParams(location.search).get('version');if(requested)await openVersion(requested);translatePage();});
