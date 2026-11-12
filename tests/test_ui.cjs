// Unit tests for UI state transitions, rendered contracts and deletion safeguards.
// This is a DOM adapter, not a replacement for a real-browser visual check.
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const elements=new Map(),listeners={};
function element(key){if(elements.has(key))return elements.get(key);const el={innerHTML:'',textContent:'',value:'',dataset:{},classList:{toggle(){},add(){},remove(){}},addEventListener(type,fn){this[type]=fn;},setAttribute(k,v){this[k]=v;},hasAttribute(){return false;},focus(){this.focused=true;},showModal(){this.open=true;},close(value){this.returnValue=value;this.open=false;this.onclose?.();},closest(){return element(key+'-parent');}};elements.set(key,el);return el;}
const document={querySelector:element,querySelectorAll:()=>[],getElementById:id=>element('#'+id),documentElement:{dataset:{}},body:{},addEventListener:(type,fn)=>listeners[type]=fn,createTreeWalker:()=>({nextNode:()=>null})};
const storage={};const context=vm.createContext({document,localStorage:{getItem:k=>storage[k]||null,setItem:(k,v)=>storage[k]=v},location:{search:'',reload(){}},MutationObserver:class{observe(){}},NodeFilter:{SHOW_TEXT:4},queueMicrotask,console,Intl,URLSearchParams,setTimeout,clearTimeout,fetch:async()=>({ok:true,json:async()=>({groups:[{id:'g',name:'General',is_default:1}],projects:[]})})});
vm.runInContext(fs.readFileSync('app/static/i18n.js','utf8'),context);
vm.runInContext(fs.readFileSync('app/static/app.js','utf8'),context);
const run=code=>vm.runInContext(code,context);
(async()=>{
 await new Promise(setImmediate);
 assert.equal(run('expanded.g'),true);
 assert.match(element('#projects').innerHTML,/General/);
 run(`state.projects=[{id:'p',group_id:'g',name:'Project',description:'Description',artifacts:[{id:'a',name:'Artifact',description:'Full description',version_count:3}]}];state.project='p';state.artifact='a';state.group='g';renderLibrary();`);
 assert.match(element('#artifacts').innerHTML,/artifact-picker/);
 assert.match(element('#artifacts').innerHTML,/Full description/);
 assert.match(element('#artifacts').innerHTML,/title="Full description"/);
 assert.match(element('#artifacts').innerHTML,/Изображение/);
 assert.doesNotMatch(element('#artifacts').innerHTML,/Фото/);
 assert.match(element('#projects').innerHTML,/icon-group/);
 run(`expanded.p=true;renderLibrary()`);
 assert.match(element('#projects').innerHTML,/icon-folder/);
 assert.match(element('#projects').innerHTML,/icon-image/);
 assert.equal(run(`artifactDescription({description:''},{description:'Project context'})`),'Project context');
 assert.equal(run(`artifactDescription({description:'Artifact context'},{description:'Project context'})`),'Artifact context');
 assert.match(run(`themeSwitch('test-theme')`),/data-theme-choice="system"/);
 assert.doesNotMatch(run(`themeSwitch('test-theme')`),/<select/);

 assert.match(element('#breadcrumb-project').textContent,/General > Project > Artifact/);
 run(`state.versions=[1,2,3].map(n=>({id:'v'+n,number:n,favorite:n!==2,note:'',created_at:'2026-11-12T00:00:00Z',metadata:{samplers:[],prompts:[],loras:[]},manifest:{files:[{role:'output',path:n===3?'clip.mp4':'test.png'}],models:[]}}));state.favorite=true;renderVersions();`);
 assert.equal(run('visibleVersions().length'),2);
 assert.match(element('#versions').innerHTML,/data-media="v1"/);
 assert.doesNotMatch(element('#versions').innerHTML,/data-media="v2"/);
 assert.match(element('#versions').innerHTML,/version-badge[^>]*title="Видео"[^]*?icon-video/);
 assert.match(element('#versions').innerHTML,/version-badge[^>]*title="Изображение"[^]*?icon-image/);
 run(`openMedia('v1')`);
 assert.equal(run('mediaItems.length'),2);
 assert.match(element('#media-stage').innerHTML,/<img/);
 run('moveMedia(1)');assert.match(element('#media-stage').innerHTML,/<video.*controls/);
 assert.equal(element('#media-next').disabled,true);
 const confirmation=run(`confirmAction('Delete','All children are deleted')`);
 assert.equal(element('#confirm-cancel').focused,true);
 element('#confirm-dialog').onkeydown({key:'Enter',preventDefault(){}});
 assert.equal(await confirmation,false);
 run(`language='en';renderVersions();setTheme('light')`);assert.match(element('#versions').innerHTML,/No recognized text prompt/);assert.equal(run(`tr('Настройки')`),'Settings');assert.equal(document.documentElement.dataset.theme,'light');
 run(`language='zh'`);assert.equal(run(`tr('Настройки')`),'设置');
 console.log('UI state tests passed: tree, picker, breadcrumbs, favorites, image/video navigation, cancel-on-Enter, themes and languages.');
})().catch(error=>{console.error(error);process.exitCode=1;});
