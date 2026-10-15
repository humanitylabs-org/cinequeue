// Real app image + live shared shell resources; shell account data is isolated.
const {chromium,webkit}=require('playwright');
const http=require('node:http'),fs=require('node:fs'),assert=require('node:assert/strict');
const out=process.env.QA_OUT, appPort=Number(process.env.APP_PORT||49334), corePort=49891;
const apps=[{id:'movies-test',name:'Movies',url:'/movies/',icon:'film',type:'service',category:'app'}];
const server=http.createServer((req,res)=>{
 const app=req.url.startsWith('/movies/');
 if(!app&&!req.url.startsWith('/wizard-os-home/')) {res.setHeader('Content-Type','application/json');return res.end(JSON.stringify(req.url.includes('/apps')?{apps}:req.url.includes('sessions')?{data:[],has_more:false}:{}));}
 const port=app?appPort:corePort,path=app?req.url.slice(7):req.url;
 const up=http.request({host:'127.0.0.1',port,path,method:req.method,headers:{...req.headers,host:'127.0.0.1:'+port,origin:'http://127.0.0.1:'+port}},r=>{res.writeHead(r.statusCode,r.headers);r.pipe(res);});
 up.on('error',e=>{res.writeHead(502);res.end(String(e));});req.pipe(up);
});
const checks=[];
function check(c,n,d){checks.push({name:n,passed:!!c,detail:d});assert(c,n+': '+JSON.stringify(d));}
(async()=>{
 await new Promise(r=>server.listen(49335,'127.0.0.1',r));fs.mkdirSync(out,{recursive:true});
 const engine=process.env.QA_ENGINE||'chromium';
 const browser=await (engine==='webkit'?webkit:chromium).launch({headless:true,...(engine==='webkit'?{}:{executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'})});
 try{
  const ctx=await browser.newContext({viewport:{width:1440,height:1000},serviceWorkers:'block'});
  await ctx.addInitScript(a=>{localStorage.setItem('wos.coached','true');localStorage.setItem('wux.apps.v1',JSON.stringify(a));},apps);
  const p=await ctx.newPage(),errors=[];p.on('pageerror',e=>errors.push(String(e)));
  await p.goto('http://127.0.0.1:49335/wizard-os-home/desktop.html?open=movies-test');
  await p.waitForTimeout(1500);
  if(!p.frames().some(f=>f.url().includes('/movies/'))) await p.evaluate(a=>window.__wux.openApp(a),apps[0]);
  await p.waitForFunction(()=>Array.from(document.querySelectorAll('iframe')).some(f=>f.contentWindow?.WizardApp?.hosted));
  const f=p.frames().find(f=>f.url().includes('/movies/'));
  await f.locator('.movie').first().waitFor();
  check(await f.title()==='Movies','document renamed');
  check(!/CineQueue|CineQ/.test(await f.locator('body').innerText()),'no old display name');
  check(await f.evaluate(()=>getComputedStyle(document.body).backgroundColor)==='rgba(0, 0, 0, 0)','hosted transparent');
  const initial=await f.evaluate(()=>__cqMovies.map(m=>m.id));
  check(initial.includes('batman-begins-2005'),'starter visible',initial);
  await f.locator('#addOpen').click();await f.locator('#addRequestInput').fill('Unsent movie draft');
  const boot=await f.evaluate(()=>performance.timeOrigin); const colors=[];
  for(const skin of ['nebula','grove','tide','ember','signal']){
   await p.evaluate(id=>WosSkin.set(id),skin);
   await f.waitForFunction(id=>WizardApp.theme.get()?.skin===id,skin);
   check(await f.locator('#addRequestInput').inputValue()==='Unsent movie draft',skin+' preserves draft');
   check(await f.evaluate(()=>performance.timeOrigin)===boot,skin+' no reload');
   colors.push(await f.locator('.movie-surface').first().evaluate(e=>getComputedStyle(e).backgroundColor));
   await f.locator('#addRequestClose').click();
   await p.screenshot({path:out+'/'+skin+'.png'});
   await f.locator('#addOpen').click();
  }
  check(new Set(colors).size===5,'cards inherit all five skins',colors);
  await f.locator('#discardDraft').click();await f.locator('#addRequestClose').click();
  await f.locator('.movie .info').first().click();await f.locator('#detail:not(.hidden)').waitFor();
  await p.screenshot({path:out+'/detail.png'});
  await f.locator('.back').click();await f.locator('#detail.hidden').waitFor({state:'attached'});
  check(await f.locator('.movie').count()>0,'detail Back returns to queue, app stays open');
  await p.setViewportSize({width:412,height:892});await p.screenshot({path:out+'/phone-window.png'});
  check(errors.length===0,'zero runtime exceptions',errors);
  await ctx.close();
  // Standalone shares the exact same central client; genuine route Back and direct add.
  const c=await browser.newContext({viewport:{width:393,height:851},isMobile:true,hasTouch:true,serviceWorkers:'block'});
  const q=await c.newPage();await q.goto('http://127.0.0.1:49335/movies/');await q.locator('.movie').first().waitFor();
  const count=await q.locator('.movie').count();
  await q.locator('#addOpen').click();await q.goBack();await q.locator('#addRequestPanel').waitFor({state:'hidden'});
  check(q.url().includes('/movies/'),'browser Back closes add sheet without exit');
  await q.locator('.movie .info').first().click();await q.goBack();await q.locator('#detail.hidden').waitFor({state:'attached'});
  check(q.url().endsWith('/movies/'),'browser Back leaves detail without exit');
  if(process.env.MUTATE==='1'){
   await q.locator('#addOpen').click();await q.locator('#addRequestInput').fill('Release Persistence 2001');await q.locator('#addRequestButton').click();
   await q.locator('#addRequestPanel').waitFor({state:'hidden'});
   await q.waitForFunction(n=>__cqMovies.length===n+1,count);
   await q.locator('.movie .info').first().click();await q.locator('.detail-watch').click();
   await q.waitForFunction(()=>__cqMovies.some(m=>m.id==='release-persistence-2001'&&m.watch_history.length===1));
   await q.reload();await q.locator('#detail:not(.hidden)').waitFor();
   check(await q.evaluate(()=>__cqMovies.find(m=>m.id==='release-persistence-2001').watch_history.length)===1,'watch history survives reload');
  }
  await q.screenshot({path:out+'/standalone-phone.png'});await c.close();
 }finally{await browser.close();server.close();fs.writeFileSync(out+'/receipt.json',JSON.stringify({engine,checks},null,2));}
 console.log(JSON.stringify(checks));
})().catch(e=>{console.error(e);server.close();process.exitCode=1});
