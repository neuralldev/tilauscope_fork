# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. It is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License
# for more details. You should have received a copy of the GNU Affero General
# Public License along with this program. If not, see
# <https://www.gnu.org/licenses/>.

# AUTHOR
# Tilau 2025-2026

#
# webclient.py
#
# ## TILAU ## Real mobile client (Phase 4) — served at '/' by TilauWebControl.
#
# A single self-contained page (no CDN, no new dependency): Catppuccin Mocha
# theme, a hand-drawn <canvas> curve (BT/ET/RoR, dual axis °C | RoR mirroring
# Artisan) and touch steppers with a wheel picker. It speaks the frozen v1 WS
# contract exactly like the /dev test page — the form factor is 100 % client
# side (wiki/RemoteControl-Protocol-v1.md §9, "mock v1 validé").
#
# Phase 4a scope: PORTRAIT phone PILOT screen — connection/auth, live curve,
# per-channel steppers + wheel picker, controller lock request, ack recalibrate,
# drum mid-roast advisory. Milestones / STOP / observer polish = 4b; deadman /
# landscape / tablet / PWA install = 4c. Kept as a Python module string so it is
# packaged with the app (PyInstaller import graph) and behaves identically in a
# frozen build and in dev.
#
# The string carries no server-side templating: the WS URL is derived at runtime
# from location.host, the pairing token from the URL hash (#pt=…), exactly as the
# /dev page. Do not add .format()/f-string substitution here (braces are JS).

CLIENT_HTML = r"""<!doctype html><html lang=fr><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover,maximum-scale=1,user-scalable=no">
<meta name=theme-color content="#1E1E2E">
<meta name=apple-mobile-web-app-capable content=yes>
<meta name=apple-mobile-web-app-status-bar-style content=black-translucent>
<meta name=apple-mobile-web-app-title content=TilauScope>
<meta name=mobile-web-app-capable content=yes>
<link rel=manifest href=/manifest.webmanifest>
<link rel=apple-touch-icon href=/apple-touch-icon.png>
<link rel=icon type=image/png href=/icon-192.png>
<title>TilauScope</title>
<style>
:root{
 --bg:#1E1E2E;--surface:#181825;--overlay:#313244;--overlay2:#45475A;
 --text:#CDD6F4;--sub:#6C7086;--blue:#89B4FA;--lav:#B4BEFE;--green:#A6E3A1;
 --red:#F38BA8;--yellow:#F9E2AF;--mauve:#CBA6F7;
 --safe-top:env(safe-area-inset-top);--safe-bot:env(safe-area-inset-bottom);
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--text);
 font:15px/1.35 -apple-system,system-ui,"Segoe UI",Roboto,sans-serif;
 overflow:hidden;user-select:none;-webkit-user-select:none}
/* 100dvh = the visible viewport on iOS Safari (accounts for the address/tool
   bars); the plain-vh line is the fallback for browsers without dvh. */
#app{display:flex;flex-direction:column;height:100vh;height:100dvh;
 padding:var(--safe-top) 0 var(--safe-bot)}
/* .main holds the observer stage (curve + readouts) and the command dock. Column
   in portrait (curve above controls), row in landscape (curve left, dock right —
   the 2-zone layout, 4c). .stage groups curve+readouts so they move together. */
.main{flex:1 1 0;min-height:0;display:flex;flex-direction:column}
.stage{flex:1 1 0;min-width:0;min-height:0;display:flex;flex-direction:column}
/* ---- header ---- */
header{display:flex;align-items:center;gap:8px;padding:7px 14px 5px;flex:0 0 auto}
.dot{width:9px;height:9px;border-radius:50%;background:var(--red);flex:0 0 auto;
 transition:background .3s}
.dot.on{background:var(--green)}.dot.grace{background:var(--yellow)}
#roaster{font-weight:600;font-size:15px;color:var(--text);
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#clock{margin-left:auto;font-variant-numeric:tabular-nums;font-size:15px;
 color:var(--sub);font-family:ui-monospace,monospace}
#phasechip{font-size:11px;color:var(--bg);background:var(--sub);border-radius:10px;
 padding:2px 8px;font-weight:600;text-transform:uppercase;letter-spacing:.4px}
/* ---- chart ---- */
/* the curve is the FLEXIBLE region: controls keep their natural height and are
   always fully visible; the curve takes whatever vertical space is left and
   shrinks on its own when more buttons appear below (4b). min-height keeps it
   readable. Using flex (not vh) avoids the vh-vs-dvh mismatch on iOS Safari. */
.chartwrap{flex:1 1 0;min-height:86px;position:relative;margin:2px 6px 0}
canvas{width:100%;height:100%;display:block}
/* ---- readouts ---- */
.reads{display:flex;justify-content:space-around;padding:5px 10px 4px;flex:0 0 auto;
 border-bottom:1px solid var(--overlay)}
.read{text-align:center}
.read .v{font-size:19px;font-weight:600;font-variant-numeric:tabular-nums;
 font-family:ui-monospace,monospace;line-height:1.1}
.read .k{font-size:10px;color:var(--sub);text-transform:uppercase;letter-spacing:.5px}
.read.bt .v{color:var(--blue)}.read.et .v{color:var(--lav)}.read.ror .v{color:var(--green)}
.read.dt{display:none}.read.dt .v{color:var(--yellow)}   /* tablet-only extra (4c) */
/* ---- controls ---- */
/* min-height:0 lets this flex child actually shrink so its own scrollbar kicks
   in instead of overflowing (and being clipped by body overflow:hidden). */
.dock{flex:0 1 auto;min-height:0;overflow-y:auto;-webkit-overflow-scrolling:touch;
 padding:8px 12px calc(8px + var(--safe-bot))}
#takeover{display:block;width:100%;padding:12px;border:0;border-radius:13px;
 background:var(--blue);color:var(--bg);font-size:16px;font-weight:600;margin:0 0 8px}
#takeover:active{filter:brightness(.92)}
#takeover.pending{background:var(--overlay);color:var(--yellow)}
#release{display:block;margin:0 auto 6px;background:none;border:0;color:var(--sub);
 font-size:13px;text-decoration:underline;padding:4px}
/* 2×2 grid of compact drag controls: slide the bar to set, release to commit,
   tap the value for the wheel picker (exact). Two per row leaves the lower dock
   free for milestones / STOP (4b). */
.grid{display:grid;grid-template-columns:1fr 1fr;gap:7px}
.cell{background:var(--surface);border:1px solid var(--overlay);border-radius:13px;
 padding:7px 10px 9px;transition:border-color .3s}
.cell.advisory{border-color:var(--yellow)}
.cell .top{display:flex;align-items:baseline;gap:5px}
.cell .name{font-size:13px;color:var(--text);font-weight:500;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cell .chain{font-size:11px;color:var(--sub)}
.cell .val{margin-left:auto;font-family:ui-monospace,monospace;font-size:18px;
 font-weight:600;font-variant-numeric:tabular-nums;color:var(--text);
 padding:1px 5px;border-radius:8px}
.cell .val:active{background:var(--overlay)}
.cell .val .u{font-size:11px;color:var(--sub);margin-left:1px}
.track{position:relative;height:30px;margin-top:6px;border-radius:9px;
 background:var(--overlay);overflow:hidden;touch-action:none;cursor:pointer}
.fill{position:absolute;left:0;top:0;bottom:0;width:0;background:var(--blue);opacity:.5}
.cell.advisory .fill{background:var(--yellow)}
.knob{position:absolute;top:5px;bottom:5px;width:5px;border-radius:3px;
 background:var(--text);transform:translateX(-50%)}
.cell.locked{opacity:.5;pointer-events:none}
.hint{color:var(--sub);font-size:11px;text-align:center;margin:7px 0 0}
/* ---- 4b: milestones + recorder ---- */
.miles{margin-top:9px}
.pips{display:flex;justify-content:center;gap:0;margin-bottom:7px}
.pip{display:flex;flex-direction:column;align-items:center;flex:1 1 0;position:relative}
.pip .dot2{width:11px;height:11px;border-radius:50%;background:var(--overlay);
 border:2px solid var(--overlay);z-index:1;transition:background .25s,border-color .25s}
.pip.done .dot2{background:var(--green);border-color:var(--green)}
.pip.next .dot2{background:var(--bg);border-color:var(--blue);
 box-shadow:0 0 0 3px rgba(137,180,250,.25)}
.pip .lbl{font-size:9px;color:var(--sub);margin-top:3px;letter-spacing:.3px}
.pip.done .lbl{color:var(--green)}.pip.next .lbl{color:var(--blue)}
/* connector line between pips */
.pip:not(:first-child)::before{content:'';position:absolute;left:-50%;top:5px;
 width:100%;height:2px;background:var(--overlay)}
.pip.done::before,.pip.next.filled::before{background:var(--green)}
.milerow{display:flex;gap:9px;align-items:stretch}
#mnext{flex:1 1 auto;padding:12px;border:0;border-radius:13px;background:var(--blue);
 color:var(--bg);font-size:16px;font-weight:600}
#mnext:active{filter:brightness(.92)}
#mnext.done{background:var(--overlay);color:var(--sub)}
#mundo{flex:0 0 52px;border:1px solid var(--overlay);border-radius:13px;
 background:var(--surface);color:var(--text);font-size:22px;line-height:1}
#mundo:disabled{opacity:.35}
#recbtn{display:block;width:100%;padding:11px;border:0;border-radius:13px;
 font-size:15px;font-weight:600;margin-top:8px;background:var(--green);color:var(--bg)}
#recbtn.rec{background:var(--red);color:var(--bg)}
#recbtn:active{filter:brightness(.92)}
.miles.hidden,#recbtn.hidden{display:none}
/* STOP bottom-sheet (reuses the wheel sheet chrome) */
#stopsheet{position:fixed;inset:0;background:rgba(17,17,27,.72);z-index:31;
 display:none;flex-direction:column;justify-content:flex-end}
#stopsheet.show{display:flex}
.schoice{display:block;width:100%;text-align:left;border:0;border-radius:14px;
 padding:14px 16px;margin-bottom:10px;background:var(--overlay);color:var(--text)}
.schoice .t{font-size:16px;font-weight:600;display:block}
.schoice .d{font-size:12px;color:var(--sub);margin-top:2px;display:block}
.schoice.save{background:var(--green)}.schoice.save .t{color:var(--bg)}
.schoice.save .d{color:rgba(30,30,46,.75)}
.schoice.save:disabled{background:var(--overlay);opacity:.55}
.schoice.save:disabled .t{color:var(--sub)}.schoice.save:disabled .d{color:var(--sub)}
.schoice.finish{background:var(--overlay)}
.scancel{display:block;width:100%;padding:14px;border:0;border-radius:12px;
 background:none;color:var(--sub);font-size:15px}
/* ---- landscape / tablet: 2-zone layout (4c) ---- */
/* curve+readouts on the left (observer), the command dock on the right under the
   thumbs. The dock scrolls on its own if tall; the curve fills the left column. */
@media (orientation:landscape){
 .main{flex-direction:row}
 .stage{flex:1 1 56%;border-right:1px solid var(--overlay)}
 .stage .reads{border-bottom:0;border-top:1px solid var(--overlay)}
 .dock{flex:1 1 44%;min-width:0;padding-top:12px}
 header{padding-bottom:5px}
 /* STOP + wheel become centered modals in landscape (spec §9) */
 #stopsheet,#wheel{justify-content:center;align-items:center;padding:20px}
 #stopsheet .sheet,#wheel .sheet{border-radius:18px;width:min(88%,430px);
  border:1px solid var(--overlay);padding-bottom:16px}
 .wscroll{height:150px}
}
/* phone in landscape: very short (~430px tall) — compact hard so the whole dock
   (grid + milestones + STOP) fits without scrolling. max-height keeps this OFF on
   tablets (which are tall even in landscape). */
@media (orientation:landscape) and (max-height:679px){
 .dock{padding-top:8px}
 #takeover{padding:9px;font-size:14px;margin-bottom:6px}
 #release{margin:0 auto 4px}
 .grid{gap:6px}
 .cell{padding:5px 8px 7px}
 .cell .name{font-size:12px}
 .cell .val{font-size:16px}
 .track{height:24px;margin-top:5px}
 .knob{top:4px;bottom:4px}
 .miles{margin-top:7px}.pips{margin-bottom:5px}
 #mnext{padding:9px;font-size:14px}
 #mundo{flex:0 0 46px;font-size:19px}
 #recbtn{padding:9px;margin-top:6px;font-size:14px}
 .hint{display:none}
}
/* tablet (≥ ~9\", tall even in landscape): more room ⇒ ΔT readout + bigger numbers.
   min-height gates OUT big phones in landscape (which are ≤ ~500px tall). */
@media (orientation:landscape) and (min-width:900px) and (min-height:680px){
 .read.dt{display:block}
 .read .v{font-size:22px}
 .cell .val{font-size:20px}
 .track{height:34px}
}
/* ---- wheel picker ---- */
#wheel{position:fixed;inset:0;background:rgba(17,17,27,.72);z-index:30;
 display:none;flex-direction:column;justify-content:flex-end}
#wheel.show{display:flex}
.sheet{background:var(--surface);border-radius:18px 18px 0 0;
 padding:14px 16px calc(16px + var(--safe-bot));border-top:1px solid var(--overlay)}
.sheet h3{margin:0 0 2px;font-size:15px;color:var(--text)}
.sheet .sub{font-size:12px;color:var(--sub);margin-bottom:8px}
.wscroll{height:210px;overflow-y:scroll;scroll-snap-type:y mandatory;
 position:relative;-webkit-overflow-scrolling:touch;
 mask-image:linear-gradient(transparent,#000 30%,#000 70%,transparent);
 -webkit-mask-image:linear-gradient(transparent,#000 30%,#000 70%,transparent)}
.wscroll .pad{height:84px}
.wopt{height:42px;scroll-snap-align:center;display:flex;align-items:center;
 justify-content:center;font-family:ui-monospace,monospace;font-size:22px;
 color:var(--sub);font-variant-numeric:tabular-nums}
.wopt.sel{color:var(--blue);font-size:26px;font-weight:600}
.wcenter{position:absolute;left:0;right:0;top:84px;height:42px;pointer-events:none;
 border-top:1px solid var(--overlay2);border-bottom:1px solid var(--overlay2)}
.wbtns{display:flex;gap:10px;margin-top:12px}
.wbtns button{flex:1;padding:14px;border:0;border-radius:12px;font-size:15px;font-weight:600}
.wcancel{background:var(--overlay);color:var(--text)}
.wok{background:var(--green);color:var(--bg)}
/* ---- toast ---- */
#toast{position:fixed;left:50%;top:calc(var(--safe-top) + 10px);transform:translateX(-50%);
 background:var(--overlay);color:var(--text);padding:9px 16px;border-radius:20px;
 font-size:13px;z-index:40;opacity:0;transition:opacity .25s;pointer-events:none;
 max-width:88%;text-align:center}
#toast.show{opacity:1}#toast.warn{background:var(--yellow);color:var(--bg)}
#toast.err{background:var(--red);color:var(--bg)}
/* ---- overlay (connecting / auth) ---- */
#veil{position:fixed;inset:0;background:var(--bg);z-index:20;display:flex;
 flex-direction:column;align-items:center;justify-content:center;gap:14px;
 padding:24px;text-align:center}
#veil.hide{display:none}
#veil .logo{font-size:20px;font-weight:700;color:var(--blue)}
#veil .msg{color:var(--sub);font-size:14px;max-width:320px}
/* pairing form — shown when the app has no token (e.g. installed to the home
   screen: iOS gives it a fresh storage jar, so it must pair on its own). */
#pairbox{display:none;flex-direction:column;gap:10px;width:min(320px,86%)}
#pairbox.show{display:flex}
#ptinput{padding:12px 14px;border-radius:12px;border:1px solid var(--overlay);
 background:var(--surface);color:var(--text);font-size:15px;text-align:center;width:100%}
#ptgo{padding:12px;border:0;border-radius:12px;background:var(--blue);color:var(--bg);
 font-size:15px;font-weight:600}
.spin{width:26px;height:26px;border:3px solid var(--overlay);border-top-color:var(--blue);
 border-radius:50%;animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
/* ---- deadman: link lost during the grace window (4c) ---- */
/* a scrim over the FROZEN screen (last curve/values stay faintly visible behind,
   nothing moves) — the desktop holds the hardware still until the grace lapses. */
#dead{position:fixed;inset:0;background:rgba(30,30,46,.86);z-index:35;display:none;
 flex-direction:column;align-items:center;justify-content:center;gap:13px;
 padding:26px;text-align:center}
#dead.show{display:flex}
#dead .brk{font-size:34px;line-height:1;filter:grayscale(1);opacity:.9}
#dead .frozen{display:inline-flex;align-items:center;gap:7px;background:rgba(166,227,161,.14);
 color:var(--green);border:1px solid var(--green);border-radius:20px;
 padding:6px 14px;font-size:14px;font-weight:600}
#dead .frozen .d2{width:8px;height:8px;border-radius:50%;background:var(--green)}
#dead .last{color:var(--sub);font-size:13px;font-family:ui-monospace,monospace}
#dead .cd{color:var(--text);font-size:14px;max-width:300px}
#dead .cd b{color:var(--yellow);font-variant-numeric:tabular-nums}
#dead .reco{margin-top:4px;padding:12px 26px;border:0;border-radius:12px;
 background:var(--blue);color:var(--bg);font-size:15px;font-weight:600}
</style>
<div id=app>
 <header>
  <span class=dot id=dot></span>
  <span id=roaster>TilauScope</span>
  <span id=phasechip>—</span>
  <span id=clock>—:—</span>
 </header>
 <div class=main>
  <div class=stage>
   <div class=chartwrap><canvas id=cv></canvas></div>
   <div class=reads>
    <div class="read bt"><div class=v id=r_bt>–</div><div class=k>BT °C</div></div>
    <div class="read et"><div class=v id=r_et>–</div><div class=k>ET °C</div></div>
    <div class="read ror"><div class=v id=r_ror>–</div><div class=k>RoR</div></div>
    <div class="read dt"><div class=v id=r_dt>–</div><div class=k>ΔT</div></div>
   </div>
  </div>
  <div class=dock>
   <button id=takeover>Prendre le contrôle</button>
   <button id=release style=display:none>Rendre le contrôle</button>
   <div class=grid id=grid></div>
   <div class="miles hidden" id=miles>
    <div class=pips id=pips></div>
    <div class=milerow>
     <button id=mundo title="Annuler le dernier jalon">‹</button>
     <button id=mnext>Marquer</button>
    </div>
   </div>
   <button id=recbtn class=hidden>Démarrer l’enregistrement</button>
   <div class=hint id=hint>Connexion…</div>
  </div>
 </div>
</div>
<div id=stopsheet><div class=sheet>
 <h3>Arrêter le roast ?</h3>
 <div class=sub>Deux façons de finir, aucune ne jette le roast.</div>
 <button class="schoice save" id=st_save><span class=t>Enregistrer</span>
  <span class=d>Sauve le .alog · complète poids et couleur au bureau</span></button>
 <button class="schoice finish" id=st_finish><span class=t>Finir sur Artisan</span>
  <span class=d>Arrête sans écrire · tu termines au bureau</span></button>
 <button class=scancel id=st_cancel>Annuler</button>
</div></div>
<div id=wheel><div class=sheet>
 <h3 id=wtitle>Réglage</h3><div class=sub id=wsub></div>
 <div class=wscroll id=wscroll><div class=wcenter></div></div>
 <div class=wbtns><button class=wcancel id=wcancel>Annuler</button>
  <button class=wok id=wok>Valider</button></div>
</div></div>
<div id=toast></div>
<div id=veil><div class=logo>TilauScope</div>
 <div class=spin id=veilspin></div>
 <div class=msg id=veilmsg>Connexion au torréfacteur…</div>
 <div id=pairbox>
  <input id=ptinput type=text autocapitalize=off autocorrect=off spellcheck=false
   placeholder="Colle le lien d’appairage">
  <button id=ptgo>Appairer</button>
 </div></div>
<div id=dead>
 <div class=brk>🔌</div>
 <div class=frozen><span class=d2></span>Matériel figé</div>
 <div class=last id=deadlast>—</div>
 <div class=cd id=deadcd>Lien perdu. Le bureau garde ta main encore <b>—</b> s.</div>
 <div class=spin></div>
 <button class=reco id=deadreco>Reconnecter</button>
</div>
<script>
"use strict";
var $=function(id){return document.getElementById(id);};
/* ---------- identity + pairing ---------- */
var PT=(location.hash.match(/pt=([^&]+)/)||[])[1];
function DN(){var u=navigator.userAgent;
 if(/iPhone/.test(u))return "iPhone";
 if(/iPad/.test(u)||(/Macintosh/.test(u)&&navigator.maxTouchPoints>1))return "iPad";
 if(/Android/.test(u))return "Android";return "Phone";}
var CID=localStorage.getItem('tcid')||('phone-'+Math.random().toString(36).slice(2,8));
localStorage.setItem('tcid',CID);

/* ---------- state ---------- */
var WS=null,sq=10,giveup=false,role='observer',pendCtl=false;
var chans=[],chById={},S={},advis={};              // slider values / advisory by channel id
var series={t:[],bt:[],et:[],ror:[]};
var markers=[],phase='idle',chargeT=null,clock=0,haveData=false;
var MARKLBL={CHARGE:'CHARGE',DRYe:'DE',DRY:'DE',FCs:'FCs',SCs:'SCs',DROP:'DROP'};
/* 4b: milestone sequence (from welcome.controls.mark) + recorder state. */
var markSeq=[],recording=false;

function send(o){if(WS&&WS.readyState===1){WS.send(JSON.stringify(o));return true;}return false;}
function cmd(payload){return send({v:1,type:'command',seq:++sq,ts:Date.now()/1000,payload:payload});}

/* ---------- toast ---------- */
var toastT=null;
function toast(msg,kind){var t=$('toast');t.textContent=msg;t.className='show'+(kind?' '+kind:'');
 clearTimeout(toastT);toastT=setTimeout(function(){t.className='';},2400);}

/* ---------- header / phase ---------- */
var PHASES={idle:['Repos','#6C7086'],preheat:['Préchauffe','#F9E2AF'],
 drying:['Séchage','#89B4FA'],maillard:['Maillard','#F9E2AF'],
 development:['Développement','#F38BA8'],cooling:['Refroid.','#A6E3A1']};
function fmtClock(){if(!haveData)return '—:—';
 // before CHARGE the timer counts preheat/monitoring time (clock starts ~0); after
 // CHARGE it counts the roast from 0.
 var s=Math.max(0,Math.round(chargeT!=null?(clock-chargeT):clock));
 return (Math.floor(s/60))+':'+('0'+(s%60)).slice(-2);}
function paintHeader(){
 var ph=PHASES[phase]||[phase,'#6C7086'];var c=$('phasechip');
 c.textContent=ph[0];c.style.background=ph[1];
 c.style.color=(ph[1]==='#6C7086'||ph[1]==='#F38BA8'||ph[1]==='#89B4FA')?'#1E1E2E':'#1E1E2E';
 $('clock').textContent=fmtClock();}

/* ---------- readouts ---------- */
function paintReads(d){
 if('bt' in d)$('r_bt').textContent=(d.bt!=null?Math.round(d.bt):'–');
 if('et' in d)$('r_et').textContent=(d.et!=null?Math.round(d.et):'–');
 if('ror' in d)$('r_ror').textContent=(d.ror!=null?d.ror.toFixed(1):'–');
 // ΔT (ET−BT) — only surfaced on tablet, but cheap to keep current
 var bt=(d.bt!=null?d.bt:lastVal('bt')),et=(d.et!=null?d.et:lastVal('et'));
 $('r_dt').textContent=(bt!=null&&et!=null)?Math.round(et-bt):'–';}

/* ---------- chart ---------- */
var cv=$('cv'),ctx=cv.getContext('2d'),DPR=Math.min(window.devicePixelRatio||1,2.5);
function sizeCanvas(){var w=cv.clientWidth,h=cv.clientHeight;
 var nw=Math.max(1,Math.round(w*DPR)),nh=Math.max(1,Math.round(h*DPR));
 // only reallocate the backing store when the size actually changed — assigning
 // cv.width/height CLEARS the canvas, so doing it on every resize event (there are
 // many during an iOS rotation) causes a flash. drawChart() always fully repaints.
 if(nw!==cv.width||nh!==cv.height){cv.width=nw;cv.height=nh;}
 drawChart();}
var _szRAF=null;
function scheduleSize(){if(_szRAF)return;
 _szRAF=requestAnimationFrame(function(){_szRAF=null;sizeCanvas();});}
function extent(a){var mn=Infinity,mx=-Infinity;for(var i=0;i<a.length;i++){var v=a[i];
 if(v==null||v!==v)continue;if(v<mn)mn=v;if(v>mx)mx=v;}
 return (mn===Infinity)?null:[mn,mx];}
function drawChart(){
 var W=cv.width,H=cv.height,PL=34*DPR,PR=42*DPR,PT_=8*DPR,PB=16*DPR;
 ctx.clearRect(0,0,W,H);
 var t=series.t,bt=series.bt,et=series.et,ror=series.ror,n=t.length;
 // domains
 var te=extent(bt.concat(et));if(!te)te=[20,220];
 var tmin=Math.floor((te[0]-8)/10)*10,tmax=Math.ceil((te[1]+8)/10)*10;
 if(tmax-tmin<40)tmax=tmin+40;
 var re=extent(ror);var rmin=0,rmax=15;if(re){rmin=Math.min(0,Math.floor(re[0]/5)*5);rmax=Math.max(15,Math.ceil(re[1]/5)*5);}
 // x-axis is a GROWING WINDOW, not a tight fit: start ~10 min wide so early data
 // isn't stretched across the screen, then extend one minute at a time keeping ~1
 // min of empty margin to the right of the latest sample.
 var xmin=t.length?t[0]:0,last=t.length?t[n-1]:0;
 var span=Math.max(600,Math.ceil((last-xmin)/60)*60+60);var xmax=xmin+span;
 function X(v){return PL+(v-xmin)/(xmax-xmin)*(W-PL-PR);}
 function YT(v){return PT_+(tmax-v)/(tmax-tmin)*(H-PT_-PB);}
 function YR(v){return PT_+(rmax-v)/(rmax-rmin)*(H-PT_-PB);}
 // phase bands (derived from markers): drying / maillard / development. The open
 // band extends to 'now' (last sample) so the current phase is shaded live.
 function mt(nm){for(var i=0;i<markers.length;i++)if(markers[i].name===nm)return markers[i].t;return null;}
 var PBANDS=[['CHARGE','DRYe','rgba(137,180,250,.06)'],
  ['DRYe','FCs','rgba(249,226,175,.06)'],['FCs','DROP','rgba(243,139,168,.07)']];
 for(var pb=0;pb<PBANDS.length;pb++){var a=mt(PBANDS[pb][0]);if(a==null)continue;
  var b=mt(PBANDS[pb][1]);var bx0=X(a),bx1=X(b!=null?b:xmax);
  if(bx1<=bx0)continue;ctx.fillStyle=PBANDS[pb][2];
  ctx.fillRect(bx0,PT_,bx1-bx0,H-PT_-PB);}
 // grid + temp axis
 ctx.font=(10*DPR)+'px ui-monospace,monospace';ctx.textBaseline='middle';
 ctx.lineWidth=1;
 for(var g=tmin;g<=tmax;g+=(tmax-tmin>120?40:20)){var y=YT(g);
  ctx.strokeStyle='rgba(49,50,68,.7)';ctx.beginPath();ctx.moveTo(PL,y);ctx.lineTo(W-PR,y);ctx.stroke();
  ctx.fillStyle='#6C7086';ctx.textAlign='right';ctx.fillText(g,PL-4*DPR,y);}
 // ror axis labels (right)
 ctx.textAlign='left';
 for(var gr=rmin;gr<=rmax;gr+=(rmax-rmin>30?10:5)){ctx.fillStyle='#586074';
  ctx.fillText(gr,W-PR+4*DPR,YR(gr));}
 // markers
 for(var mi=0;mi<markers.length;mi++){var mk=markers[mi];if(mk.t==null)continue;
  var mx=X(mk.t);if(mx<PL||mx>W-PR)continue;
  ctx.strokeStyle='rgba(108,112,134,.55)';ctx.setLineDash([3*DPR,3*DPR]);
  ctx.beginPath();ctx.moveTo(mx,PT_);ctx.lineTo(mx,H-PB);ctx.stroke();ctx.setLineDash([]);
  ctx.fillStyle='#6C7086';ctx.textAlign='center';
  ctx.fillText(MARKLBL[mk.name]||mk.name,mx,PT_+7*DPR);}
 function line(arr,Y,color,w){ctx.strokeStyle=color;ctx.lineWidth=w*DPR;ctx.lineJoin='round';
  ctx.beginPath();var started=false;
  for(var i=0;i<n;i++){var v=arr[i];if(v==null||v!==v){started=false;continue;}
   var px=X(t[i]),py=Y(v);if(!started){ctx.moveTo(px,py);started=true;}else ctx.lineTo(px,py);}
  ctx.stroke();}
 line(ror,YR,'#A6E3A1',1.5);
 line(et,YT,'#B4BEFE',1.5);
 line(bt,YT,'#89B4FA',2.2);
 // current BT dot + phase annotation
 if(n){var lbt=null,li=n-1;while(li>=0&&(bt[li]==null||bt[li]!==bt[li]))li--;
  if(li>=0){lbt=bt[li];var cx=X(t[li]),cy=YT(lbt);
   ctx.fillStyle='#89B4FA';ctx.beginPath();ctx.arc(cx,cy,3.2*DPR,0,6.29);ctx.fill();}}
}

/* ---------- controls: 2×2 drag grid ---------- */
function clampStep(ch,v){var mn=ch.min!=null?ch.min:0,mx=ch.max!=null?ch.max:100,st=ch.step||1;
 v=Math.round((v-mn)/st)*st+mn;return Math.max(mn,Math.min(mx,v));}
function frac(ch){var mn=ch.min!=null?ch.min:0,mx=ch.max!=null?ch.max:100,v=S[ch.id];
 if(v==null)return 0;return Math.max(0,Math.min(1,(v-mn)/((mx-mn)||1)));}
function buildGrid(){
 var box=$('grid');box.innerHTML='';chById={};
 chans.forEach(function(ch){chById[ch.id]=ch;
  var c=document.createElement('div');c.className='cell';c.id='c_'+ch.id;
  var top=document.createElement('div');top.className='top';
  var nm=document.createElement('span');nm.className='name';nm.textContent=ch.label;top.appendChild(nm);
  if(ch.coupled){var q=document.createElement('span');q.className='chain';q.textContent='⛓';top.appendChild(q);}
  var val=document.createElement('span');val.className='val';val.id='val_'+ch.id;
  val.innerHTML='–<span class=u>%</span>';
  val.addEventListener('click',function(){if(role==='controller')openWheel(ch);});
  top.appendChild(val);c.appendChild(top);
  var tr=document.createElement('div');tr.className='track';tr.id='tr_'+ch.id;
  var fl=document.createElement('div');fl.className='fill';fl.id='fl_'+ch.id;tr.appendChild(fl);
  var kb=document.createElement('div');kb.className='knob';kb.id='kb_'+ch.id;tr.appendChild(kb);
  attachDrag(tr,ch);c.appendChild(tr);box.appendChild(c);});
 refresh();applyRole();
}
function refresh(){chans.forEach(function(ch){
  var e=$('val_'+ch.id);if(e)e.innerHTML=(S[ch.id]==null?'–':Math.round(S[ch.id]))
   +'<span class=u>'+(ch.unit||'%')+'</span>';
  var p=frac(ch)*100,fl=$('fl_'+ch.id),kb=$('kb_'+ch.id);
  if(fl)fl.style.width=p+'%';if(kb)kb.style.left=p+'%';});}
function applyRole(){var ctl=role==='controller';
 chans.forEach(function(ch){var c=$('c_'+ch.id);if(c)c.classList.toggle('locked',!ctl);});
 $('takeover').style.display=ctl?'none':'block';
 $('release').style.display=ctl?'block':'none';
 $('hint').textContent=ctl?'Glisse pour régler · tap la valeur = molette'
  :(haveData?'Observateur · prends le contrôle pour piloter':'Connexion…');}
/* drag: the value follows the finger locally only (no traffic while sliding);
   a single set_slider(final:true) is sent on release, and only if the value
   actually changed from where the drag started. */
function attachDrag(tr,ch){var dragging=false,startVal=null;
 function valAt(x){var r=tr.getBoundingClientRect();var f=(x-r.left)/((r.width)||1);
  f=Math.max(0,Math.min(1,f));var mn=ch.min!=null?ch.min:0,mx=ch.max!=null?ch.max:100;
  return clampStep(ch,mn+f*(mx-mn));}
 function live(x){var v=valAt(x);if(v!==S[ch.id]){S[ch.id]=v;refresh();}}
 function down(e){if(role!=='controller')return;dragging=true;startVal=S[ch.id];
  try{tr.setPointerCapture(e.pointerId);}catch(x){}live(e.clientX);}
 function move(e){if(dragging)live(e.clientX);}
 function up(){if(!dragging)return;dragging=false;var v=S[ch.id];
  if(v!=null&&v!==startVal)cmd({action:'set_slider',channel:ch.id,value:v,final:true});}
 tr.addEventListener('pointerdown',down);tr.addEventListener('pointermove',move);
 tr.addEventListener('pointerup',up);tr.addEventListener('pointercancel',up);
}
function setChan(ch,v){v=clampStep(ch,v);if(v===S[ch.id])return;S[ch.id]=v;refresh();
 cmd({action:'set_slider',channel:ch.id,value:v,final:true});}

/* ---------- 4b: milestones (contextual next + undo last) ---------- */
var nextMile=null,undoMile=null;
function isMarked(name){return markers.some(function(m){return m.name===name;});}
function renderMiles(){
 var box=$('miles');
 if(!markSeq.length){box.classList.add('hidden');return;}
 box.classList.remove('hidden');
 // next = first unmarked in the sequence; undo target = last marked so far.
 nextMile=null;undoMile=null;
 for(var i=0;i<markSeq.length;i++){if(!isMarked(markSeq[i])){nextMile=markSeq[i];break;}}
 for(var j=markSeq.length-1;j>=0;j--){if(isMarked(markSeq[j])){undoMile=markSeq[j];break;}}
 // pips
 var pips=$('pips');pips.innerHTML='';
 markSeq.forEach(function(name){
  var done=isMarked(name),isnext=(name===nextMile);
  var p=document.createElement('div');p.className='pip'+(done?' done':'')+(isnext?' next':'');
  if(isnext&&undoMile)p.className+=' filled';
  p.innerHTML='<span class=dot2></span><span class=lbl>'+(MARKLBL[name]||name)+'</span>';
  pips.appendChild(p);});
 // buttons
 var ctl=role==='controller';
 var mn=$('mnext'),mu=$('mundo');
 mn.style.display=ctl?'':'none';mu.style.display=ctl?'':'none';
 if(nextMile){mn.textContent='Marquer '+(MARKLBL[nextMile]||nextMile);mn.classList.remove('done');}
 else{mn.textContent='Roast complet';mn.classList.add('done');}
 mu.disabled=!undoMile;
}
/* ---------- 4b: recorder start / stop ---------- */
function renderRec(){
 var b=$('recbtn'),ctl=role==='controller';
 if(!ctl){b.classList.add('hidden');return;}
 b.classList.remove('hidden');
 if(recording){b.classList.add('rec');b.textContent='STOP';}
 else{b.classList.remove('rec');b.textContent='Démarrer l’enregistrement';}
}
function render4b(){renderMiles();renderRec();}

/* ---------- wheel picker ---------- */
var wheelCh=null;
function openWheel(ch){wheelCh=ch;$('wtitle').textContent=ch.label;
 $('wsub').textContent='Glisse jusqu’à la valeur, puis Valider';
 var sc=$('wscroll');sc.querySelectorAll('.wopt,.pad').forEach(function(e){e.remove()});
 var mn=ch.min!=null?ch.min:0,mx=ch.max!=null?ch.max:100,st=ch.step||1;
 var top=document.createElement('div');top.className='pad';sc.appendChild(top);
 var cur=S[ch.id]!=null?S[ch.id]:mn,curEl=null;
 for(var v=mn;v<=mx+1e-9;v+=st){var o=document.createElement('div');o.className='wopt';
  o.textContent=Math.round(v);o.dataset.v=v;sc.appendChild(o);if(Math.abs(v-cur)<st/2)curEl=o;}
 var bot=document.createElement('div');bot.className='pad';sc.appendChild(bot);
 $('wheel').classList.add('show');
 requestAnimationFrame(function(){if(curEl)sc.scrollTop=curEl.offsetTop-84;markSel();});}
function markSel(){var sc=$('wscroll'),mid=sc.scrollTop+84+21,best=null,bd=1e9;
 sc.querySelectorAll('.wopt').forEach(function(o){o.classList.remove('sel');
  var c=o.offsetTop+21,dd=Math.abs(c-mid);if(dd<bd){bd=dd;best=o;}});
 if(best)best.classList.add('sel');return best;}
var wheelRAF=null;
$('wscroll').addEventListener('scroll',function(){if(wheelRAF)return;
 wheelRAF=requestAnimationFrame(function(){wheelRAF=null;markSel();});});
$('wcancel').onclick=function(){$('wheel').classList.remove('show');wheelCh=null;};
$('wok').onclick=function(){var b=markSel();if(b&&wheelCh)setChan(wheelCh,+b.dataset.v);
 $('wheel').classList.remove('show');wheelCh=null;};

/* ---------- control lock ---------- */
$('takeover').onclick=function(){if(pendCtl)return;
 if(!cmd({action:'request_control'})){toast('Hors ligne',' err');return;}
 pendCtl=true;var b=$('takeover');b.classList.add('pending');
 b.textContent='Demande envoyée · confirme sur le bureau…';};
$('release').onclick=function(){cmd({action:'release_control'});};
function setRole(r){role=r;pendCtl=false;var b=$('takeover');b.classList.remove('pending');
 b.textContent='Prendre le contrôle';applyRole();render4b();}

/* ---------- 4b button wiring ---------- */
$('mnext').onclick=function(){if(role!=='controller'||!nextMile)return;
 cmd({action:'mark',milestone:nextMile});};
$('mundo').onclick=function(){if(role!=='controller'||!undoMile)return;
 // re-emitting the mark toggles it OFF on the desktop (same as the mark button);
 // the milestone 'removed' event will refresh the pips.
 cmd({action:'mark',milestone:undoMile});};
$('recbtn').onclick=function(){if(role!=='controller')return;
 if(recording)openStop();else cmd({action:'recorder',op:'start'});};
function canSave(){return isMarked('CHARGE')&&isMarked('DROP');}
function openStop(){var ok=canSave();var s=$('st_save');s.disabled=!ok;
 s.title=ok?'':'CHARGE et DROP requis pour enregistrer';
 $('stopsheet').classList.add('show');}
function closeStop(){$('stopsheet').classList.remove('show');}
$('st_save').onclick=function(){if(!canSave())return;
 cmd({action:'recorder',op:'stop',save:true});closeStop();};
$('st_finish').onclick=function(){cmd({action:'recorder',op:'stop',save:false});closeStop();};
$('st_cancel').onclick=closeStop;

/* ---------- ingest ---------- */
function ingestSliders(sl){if(!sl)return;for(var k in sl)S[k]=sl[k];refresh();}
function setSnapshot(d){
 series={t:(d.series&&d.series.t)||[],bt:(d.series&&d.series.bt)||[],
  et:(d.series&&d.series.et)||[],ror:(d.series&&d.series.ror)||[]};
 markers=d.markers||[];phase=d.phase||'idle';clock=d.clock||0;
 // snapshot series are charge-relative but clock is session-absolute; recover the
 // absolute charge time as clock - lastSeriesT so the roast timer matches telemetry.
 var lt=series.t.length?series.t[series.t.length-1]:0;
 chargeT=d.charge_marked?(clock-lt):null;
 recording=!!d.recording;
 ingestSliders(d.sliders);haveData=true;
 paintHeader();paintReads({bt:lastVal('bt'),et:lastVal('et'),ror:lastVal('ror')});
 drawChart();applyRole();render4b();}
function lastVal(k){var a=series[k];for(var i=a.length-1;i>=0;i--)if(a[i]!=null&&a[i]===a[i])return a[i];return null;}
function pushTele(d){
 var x=(d.t!=null?d.t:(d.clock!=null?d.clock:clock));
 series.t.push(x);series.bt.push(d.bt);series.et.push(d.et);series.ror.push(d.ror);
 if(series.t.length>1400){['t','bt','et','ror'].forEach(function(k){series[k].shift();});}
 if(d.phase)phase=d.phase;if(d.clock!=null)clock=d.clock;
 if(d.t!=null&&chargeT==null)chargeT=clock-d.t;
 ingestSliders(d.sliders);haveData=true;
 paintHeader();paintReads(d);drawChart();}

/* ---------- events ---------- */
function onEvent(d){
 if(d.kind==='control'){
  if(d.state==='granted'){setRole('controller');toast('Tu pilotes','warn');}
  else if(d.state==='released'){setRole('observer');}
  else if(d.state==='revoked'){setRole('observer');toast('Contrôle repris ailleurs','warn');}
  return;}
 if(d.kind==='milestone'){var m=MARKLBL[d.name]||d.name;
  if(d.state==='removed'){
   markers=markers.filter(function(x){return x.name!==d.name;});
   toast(m+' annulé','warn');}
  else{
   if(!markers.some(function(x){return x.name===d.name;}))markers.push({name:d.name,t:d.t});
   toast(m+' marqué','warn');}
  drawChart();render4b();return;}
 if(d.kind==='recorder'){
  if(d.state==='started'){recording=true;toast('Enregistrement démarré','warn');}
  else if(d.state==='stopped'){recording=false;
   if(d.saved===true)toast('Roast enregistré','warn');
   else toast('Enregistrement arrêté','warn');}
  render4b();return;}
}
function onAck(d){
 if(d.channel&&d.applied_value!=null){S[d.channel]=d.applied_value;refresh();}
 if(d.channel&&('advisory' in d)){var f=$('c_'+d.channel);
  if(f){var on=d.advisory==='drum_midroast';f.classList.toggle('advisory',on);
   if(on){clearTimeout(advis[d.channel]);
    advis[d.channel]=setTimeout(function(){var g=$('c_'+d.channel);if(g)g.classList.remove('advisory');},4000);}}}
 // a STOP-with-save may succeed as STOP yet fail to write (status ok, saved:false)
 if(d.saved===false&&d.reason){
  if(d.reason==='INCOMPLETE_ROAST')toast('CHARGE et DROP requis pour enregistrer','warn');
  else if(d.reason==='NOTHING_TO_SAVE')toast('Rien à enregistrer','warn');}
 if(d.status==='rejected'){
  if(d.reason==='NOT_CONTROLLER'&&pendCtl){pendCtl=false;var b=$('takeover');
   b.classList.remove('pending');b.textContent='Prendre le contrôle';toast('Contrôle refusé','err');}
  else if(d.reason==='RATE_LIMITED')toast('Occupé, réessaie','warn');
  else if(d.reason==='CHANNEL_READONLY')toast('Réglage en lecture seule','warn');
  else if(d.reason==='NOT_CONTROLLER')toast('Prends d’abord le contrôle','warn');}
}

/* ---------- deadman: link lost during the grace window (4c) ---------- */
/* the desktop holds the hardware frozen for the control grace (~10 s) after a
   controller drops (webcontrol _GRACE_S) — reassure the pilot that nothing moves,
   count that window down, keep trying to reconnect. */
var GRACE=10,deadCD=0,deadTimer=null,reconnTimer=null;
function paintDead(){var cd=$('deadcd');
 if(deadCD>0)cd.innerHTML='Lien perdu. Le bureau garde ta main encore <b>'+deadCD+'</b> s.';
 else cd.innerHTML='Grâce écoulée · le matériel reste figé, le contrôle peut être repris.';}
function showDead(){if(giveup)return;
 var bt=lastVal('bt'),et=lastVal('et');
 var s=(bt!=null?'BT '+Math.round(bt)+'°':'')+(et!=null?'   ET '+Math.round(et)+'°':'');
 $('deadlast').textContent=s||'—';
 deadCD=GRACE;paintDead();$('dead').classList.add('show');
 clearInterval(deadTimer);deadTimer=setInterval(function(){deadCD--;paintDead();
  if(deadCD<=0)clearInterval(deadTimer);},1000);}
function hideDead(){clearInterval(deadTimer);$('dead').classList.remove('show');}
$('deadreco').onclick=function(){clearTimeout(reconnTimer);connect();};

/* ---------- connection ---------- */
function veil(show,msg){var v=$('veil');if(msg)$('veilmsg').textContent=msg;
 v.classList.toggle('hide',!show);
 if(show){$('pairbox').classList.remove('show');$('veilspin').style.display='';}}
/* no token (typically the home-screen app in its own storage jar) — let the user
   pair from inside the app by pasting the pairing link (TilauScope ▸ Appairer). */
function showPairForm(msg){$('veilmsg').textContent=msg;$('veil').classList.remove('hide');
 $('veilspin').style.display='none';$('pairbox').classList.add('show');}
$('ptgo').onclick=function(){var raw=$('ptinput').value.trim();if(!raw)return;
 var m=raw.match(/pt=([^&\s]+)/);PT=m?m[1]:raw;
 giveup=false;veil(true,'Appairage…');connect();};
$('ptinput').addEventListener('keydown',function(e){if(e.key==='Enter')$('ptgo').click();});
function setDot(cls){$('dot').className='dot'+(cls?' '+cls:'');}
function connect(){
 clearTimeout(reconnTimer);
 var ws;try{ws=new WebSocket('ws://'+location.host+'/ws');}catch(e){reconnTimer=setTimeout(connect,2000);return;}
 ws.onopen=function(){WS=ws;setDot('on');
  ws.send(JSON.stringify({v:1,type:'hello',seq:1,ts:Date.now()/1000,
   payload:{client_id:CID,client_ver:'1',proto_min:1,proto_max:1}}));
  var DT=localStorage.getItem('tdt');
  if(DT)ws.send(JSON.stringify({v:1,type:'auth',seq:2,ts:Date.now()/1000,
   payload:{device_id:CID,device_token:DT}}));
  else if(PT)ws.send(JSON.stringify({v:1,type:'auth',seq:2,ts:Date.now()/1000,
   payload:{token:PT,device_id:CID,display_name:DN()}}));
  else{showPairForm('Pour piloter depuis cette app, colle le lien d’appairage (TilauScope ▸ Appairer un téléphone ▸ Copier le lien).');
   giveup=true;try{ws.close();}catch(e){}}};
 ws.onmessage=function(e){var m;try{m=JSON.parse(e.data);}catch(x){return;}var d=m.payload||{};
  switch(m.type){
   case 'paired':localStorage.setItem('tdt',d.device_token);if(d.role)role=d.role;break;
   case 'welcome':
    if(d.roaster)$('roaster').textContent=d.roaster;
    chans=(d.channels||[]).filter(function(c){return c.id!=='sv';});
    // 4b milestone sequence (desktop already trims to the amateur set per operator
    // level); keep only names we can label, preserving order.
    var mk=(d.controls&&d.controls.mark)||['CHARGE','DRYe','FCs','SCs','DROP'];
    markSeq=mk.filter(function(n){return MARKLBL[n];});
    role=d.role||'observer';buildGrid();render4b();veil(false);hideDead();break;
   case 'snapshot':setSnapshot(d);break;
   case 'telemetry':pushTele(d);break;
   case 'event':onEvent(d);break;
   case 'ack':onAck(d);break;
   case 'heartbeat':if(d.clock!=null){clock=d.clock;paintHeader();}break;
   case 'error':
    if(d.code==='AUTH_FAILED'){localStorage.removeItem('tdt');giveup=true;
     showPairForm('Appairage expiré ou révoqué. Colle un nouveau lien d’appairage depuis TilauScope.');}
    else toast(d.code||'Erreur','err');break;
  }};
 ws.onclose=function(){WS=null;setDot('');
  if(!giveup){setDot('grace');$('hint').textContent='Reconnexion…';
   if(haveData)showDead();reconnTimer=setTimeout(connect,1800);}};
 ws.onerror=function(){try{ws.close();}catch(e){}};
}
window.addEventListener('resize',scheduleSize);
/* iOS settles the layout (URL bar, dvh) over ~1s after a rotation — re-fit a few
   times so the canvas lands on the final size instead of a transient one. */
window.addEventListener('orientationchange',function(){
 [60,250,600,1000].forEach(function(ms){setTimeout(scheduleSize,ms);});});
/* the curve is flex:1 1 0, so its box changes whenever the controls below grow
   or shrink (grid built, role toggled, 4b buttons); re-fit the canvas then. No
   feedback loop: the canvas CSS box is 100%/100%, unaffected by its .width. */
if(window.ResizeObserver){var ro=new ResizeObserver(scheduleSize);
 ro.observe(document.querySelector('.chartwrap'));}
sizeCanvas();connect();
</script>
"""
