const fn = eval(require('fs').readFileSync(__dirname+'/wfcheck.js','utf8'));
function run(scn){ let n=0; const calls=[];
 const fake=(s)=>{ if(!s) return 'report'; const o={}; for(const [k,v] of Object.entries(s.properties)) o[k]=v.type==='boolean'?false:v.type==='array'?[]:'x'; return o };
 const agent=async(p,o)=>{ calls.push(o.label+(o.model?'@'+o.model:'')); const r=fake(o.schema);
  if(o.label==='bootstrap'||o.label==='pin'){r.ready=true;r.ran_codex=true;r.rules_sha='P';r.datasets_approved=(scn!=='noapprove')}
  if(o.label.startsWith('measure')){n++;r.round_id='WF0'+n;r.rules_sha=(scn==='drift'&&n==2)?'Q':'P';r.profile_ok=!(scn==='noprofile'&&n==2);r.pending_merge=(scn==='merge'&&n==2)||(scn==='badmerge'&&n==2)}
  if(o.label.startsWith('plan')){r.line=(scn==='merge'&&n==2)?'merge':'trading';r.scope='common'}
  if(o.label.startsWith('verify')||o.label==='bootstrap:verify')r.ok=true;
  if(o.label.startsWith('run'))r.finished=true;
  if(o.label.startsWith('record'))r.verdict=(scn==='merge'&&n==1)?'accepted':'branch';
  return r};
 return fn({rounds:3},agent,async ts=>Promise.all(ts.map(t=>t())),null,()=>{},()=>{}).then(r=>console.log(scn,'->',JSON.stringify(r.stop),'| agents',calls.length,'| opus',calls.filter(c=>c.includes('@opus')).length));}
(async()=>{for(const s of ['same','drift','merge','badmerge','noapprove','noprofile']) await run(s)})();
