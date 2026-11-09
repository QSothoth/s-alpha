const fn = eval(require('fs').readFileSync(__dirname+'/wfcheck.js','utf8'));
async function run(name,args,planLine){ let n=0; const calls=[];
 const agent=async(p,o)=>{ calls.push(o.label); const r={}; if(o.schema) for(const [k,v] of Object.entries(o.schema.properties)) r[k]=v.type==='boolean'?false:v.type==='array'?[]:'x'; else return 'report';
  if(o.label==='bootstrap'){r.ready=true;r.rules_sha='P';r.datasets_approved=true}
  if(o.label.startsWith('measure')){n++;r.round_id='WF0'+n;r.rules_sha='P';r.profile_ok=true;r.pending_merge=n>1}
  if(o.label.startsWith('plan')){r.line=planLine(n);r.scope='common'}
  if(o.label.startsWith('verify'))r.ok=true; if(o.label.startsWith('run'))r.finished=true;
  if(o.label.startsWith('record'))r.verdict=n===1?'accepted':(n===2?'branch':'accepted');
  return r};
 const r=await fn(args,agent,null,null,()=>{},()=>{}); console.log(name,'->',JSON.stringify(r.stop||r),'| agents',calls.length);}
(async()=>{
 await run('line=selection',{rounds:3,line:'selection'},()=> 'selection')
 await run('line=selection but plan trading',{rounds:3,line:'selection'},()=> 'trading')
 await run('bad line',{line:'foo'},()=> 'selection')
 await run('line=joint',{rounds:3,line:'joint'},()=> 'joint')
 await run('pending merge, plan joint',{rounds:2},n=> n===1?'selection':'joint')
 await run('scope mismatch',{line:'selection',scope:'offense'},()=> 'selection')
})()
