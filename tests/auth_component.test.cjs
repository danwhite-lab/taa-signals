const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const {webcrypto}=require('node:crypto');
const source=fs.readFileSync(path.join(__dirname,'../src/haa/auth_component/index.html'),'utf8').split('<script>')[1].split('</script>')[0];

function harness({saved=null,callback=false}={}) {
  const listeners={}, outputs=[], calls=[], store=new Map();
  if(saved) store.set('taa-signals.auth.example.supabase.co',JSON.stringify(saved));
  const elements={login:{hidden:true},message:{textContent:''}};
  const popup={location:null,close(){}};
  let closed=false;
  let loginStyle=null;
  const head={querySelector:()=>loginStyle,appendChild:style=>loginStyle=style};
  const parent={document:{head,createElement:()=>({remove:()=>loginStyle=null})},innerHeight:800,location:{href:'https://app.example/'+(callback?'?code=callback-code':'')},postMessage:data=>outputs.push(data),close:()=>closed=true};
  if(callback) parent.opener={postMessage:(data,origin)=>calls.push({data,origin})};
  const sandbox={
    URL, URLSearchParams, TextEncoder, Uint8Array, JSON, Date, crypto:webcrypto,
    btoa:s=>Buffer.from(s,'binary').toString('base64'), navigator:{},
    setInterval:()=>0,
    localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},
    document:{getElementById:id=>elements[id]},
    window:{parent,location:{origin:'https://app.example'},open:()=>popup,addEventListener:(name,fn)=>listeners[name]=fn},
    fetch:async(url,options)=>{
      calls.push({url,options});
      return {ok:true,status:200,json:async()=>({access_token:'verified-later-by-server',refresh_token:'refresh',expires_in:3600})};
    },
  };
  vm.runInNewContext(source,sandbox);
  const render=extra=>listeners.message({source:parent,data:{type:'streamlit:render',args:{url:'https://example.supabase.co',publishable_key:'public-key',logout_version:0,...extra}}});
  return {listeners,outputs,calls,store,elements,popup,sandbox,render,isClosed:()=>closed,getStyle:()=>loginStyle};
}

test('PKCE binds the code to the verifier and rejects unexpected messages',async()=>{
  const h=harness();await h.render();
  assert.equal(h.elements.login.hidden,false);
  assert.ok(h.getStyle());
  assert.equal(h.outputs.at(-1).height,800);
  await h.elements.login.onclick();
  const authorization=new URL(h.popup.location);
  assert.equal(authorization.searchParams.get('provider'),'google');
  assert.equal(authorization.searchParams.get('redirect_to'),'https://app.example/');
  assert.equal(authorization.searchParams.get('code_challenge_method'),'s256');
  await h.listeners.message({origin:'https://attacker.example',source:h.popup,data:{type:'taa-oauth-code',code:'bad'}});
  assert.equal(h.calls.length,0);
  await h.listeners.message({origin:'https://app.example',source:h.popup,data:{type:'taa-oauth-code',code:'good'}});
  const body=JSON.parse(h.calls[0].options.body);
  assert.equal(body.auth_code,'good');
  const hash=Buffer.from(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(body.code_verifier))).toString('base64url');
  assert.equal(hash,authorization.searchParams.get('code_challenge'));
  assert.equal(h.elements.login.hidden,true);
  assert.equal(h.getStyle(),null);
  assert.ok(h.store.size);
});

test('popup callback returns only the authorization code to the initiating origin',async()=>{
  const h=harness({callback:true});await h.render();
  assert.deepEqual(JSON.parse(JSON.stringify(h.calls[0])),{data:{type:'taa-oauth-code',code:'callback-code'},origin:'https://app.example'});
  assert.equal(h.isClosed(),true);
  assert.equal(h.store.size,0);
});

test('restores a browser session and clears it on logout including component remount',async()=>{
  const saved={access_token:'access',refresh_token:'refresh',expires_at:Math.floor(Date.now()/1000)+3600};
  const h=harness({saved});await h.render();
  assert.equal(h.elements.login.hidden,true);
  await h.render({logout_version:1});
  assert.equal(h.store.size,0);
  assert.equal(h.elements.login.hidden,false);
  const remount=harness({saved});await remount.render({logout_version:1,logout_pending:true});
  assert.equal(remount.store.size,0);
});

test('rotates an expired session without putting tokens in the URL',async()=>{
  const h=harness({saved:{access_token:'expired',refresh_token:'old-refresh',expires_at:0}});
  await h.render();
  assert.ok(h.calls[0].url.endsWith('token?grant_type=refresh_token'));
  assert.equal(JSON.parse(h.calls[0].options.body).refresh_token,'old-refresh');
  assert.equal(h.sandbox.window.parent.location.href,'https://app.example/');
  assert.equal(h.elements.login.hidden,true);
});

test('completes via the same-origin callback event if the provider severs opener',async()=>{
  const h=harness();await h.render();await h.elements.login.onclick();
  await h.listeners.storage({key:'taa-signals.auth.example.supabase.co.callback',newValue:JSON.stringify({code:'storage-code'})});
  assert.equal(JSON.parse(h.calls[0].options.body).auth_code,'storage-code');
  assert.equal(h.elements.login.hidden,true);
});
