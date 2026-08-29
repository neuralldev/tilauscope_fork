(function(){
  "use strict";
  var C = {ink3:"#8e877d", ink2:"#c8c0b3", line:"#37332c", grid:"rgba(243,238,228,.075)",
           ember:"#e38245", ror:"#d8c689", bt:"#eea068", blue:"#73aab6", mark:"#d98571"};

  function svg(w,h){
    var s=document.createElementNS("http://www.w3.org/2000/svg","svg");
    s.setAttribute("viewBox","0 0 "+w+" "+h);
    s.setAttribute("width","100%"); s.setAttribute("role","img");
    s.setAttribute("class","fig-svg--narrow");
    return s;
  }
  function el(tag,attrs){
    var e=document.createElementNS("http://www.w3.org/2000/svg",tag);
    for(var k in attrs) e.setAttribute(k,attrs[k]);
    return e;
  }
  function text(x,y,str,cls,anchor){
    var t=el("text",{x:x,y:y,class:cls||"svg-lbl"});
    if(anchor) t.setAttribute("text-anchor",anchor);
    t.textContent=str; return t;
  }
  function mmss(s){ return Math.floor(s/60)+":"+String(Math.round(s%60)).padStart(2,"0"); }

  /* ---------- Figure 2 — the envelope ---------- */
  (function(){
    var host=document.getElementById("fig-env"); if(!host) return;
    var W=760,H=330,L=52,R=22,T=22,B=42;
    var ror=[[90,4.91],[120,13.55],[150,15.20],[180,15.27],[210,14.27],[240,13.47],[270,13.00],
             [300,12.38],[330,11.64],[360,10.93],[390,10.54],[420,9.90],[450,9.73],[480,9.26],
             [510,8.98],[540,9.01],[570,8.43],[600,7.57],[630,6.76],[660,5.63],[689,5.60]];
    var marks=[[75,"TP",null],[342,"DRY END",11.2],[576,"FIRST CRACK",8.4],[689,"DROP",5.6]];
    var xmax=700, ymax=18;
    var X=function(t){return L+(t/xmax)*(W-L-R);};
    var Y=function(v){return T+(1-v/ymax)*(H-T-B);};
    var s=svg(W,H);
    s.appendChild(el("title",{})).textContent="Median rate of rise across thirty 400 g roasts";
    for(var v=0;v<=ymax;v+=3){
      s.appendChild(el("line",{x1:L,y1:Y(v),x2:W-R,y2:Y(v),stroke:C.grid,"stroke-width":1}));
      s.appendChild(text(L-9,Y(v)+3.5,String(v),"svg-lbl","end"));
    }
    s.appendChild(text(L-9,Y(ymax)-9,"°C/min","svg-lbl","end"));
    for(var t=0;t<=xmax;t+=120){
      s.appendChild(text(X(t),H-B+18,mmss(t),"svg-lbl","middle"));
    }
    // ceiling
    s.appendChild(el("line",{x1:L,y1:Y(16.2),x2:W-R,y2:Y(16.2),stroke:C.ember,
      "stroke-width":1,"stroke-dasharray":"2 5","opacity":".55"}));
    s.appendChild(text(W-R,Y(16.2)-7,"typical peak 16.2","svg-lbl","end"));
    // curve
    var pts=ror.map(function(p){return X(p[0])+","+Y(p[1]);}).join(" ");
    s.appendChild(el("polyline",{points:pts,fill:"none",stroke:C.ror,"stroke-width":2.6,
      "stroke-linejoin":"round","stroke-linecap":"round"}));
    // milestones
    marks.forEach(function(m){
      var x=X(m[0]);
      s.appendChild(el("line",{x1:x,y1:T,x2:x,y2:H-B,stroke:C.line,"stroke-width":1}));
      s.appendChild(text(x+5,T+11,m[1],"svg-lbl-em"));
      if(m[2]!==null){
        s.appendChild(el("circle",{cx:x,cy:Y(m[2]),r:4,fill:C.ember,stroke:"#0d0d0c","stroke-width":1.5}));
        s.appendChild(text(x+8,Y(m[2])-8,m[2].toFixed(1),"svg-note"));
      }
    });
    s.appendChild(el("line",{x1:L,y1:H-B,x2:W-R,y2:H-B,stroke:C.line,"stroke-width":1}));
    host.appendChild(s);
  })();

  /* ---------- Figure 3 — same conduct, different arrival ---------- */
  (function(){
    var host=document.getElementById("fig-arr"); if(!host) return;
    var W=760,H=340,L=52,R=118,T=22,B=42;
    var clair=[183.7,116.7,94.9,95.6,102.2,110.2,118.0,125.2,131.8,137.8,143.6,148.8,153.6,
               158.3,162.8,167.0,171.2,175.0,179.0,183.0,187.1,191.2,193.4,195.1];
    var med  =[183.7,116.2,94.0,94.9,100.4,108.1,116.3,123.3,129.7,136.6,142.7,148.7,154.1,
               159.4,165.0,170.0,174.6,179.4,184.1,188.9,192.7,195.4,196.5,199.7];
    var step=30, xmax=700, ymin=88, ymax=210;
    var X=function(t){return L+(t/xmax)*(W-L-R);};
    var Y=function(v){return T+(1-(v-ymin)/(ymax-ymin))*(H-T-B);};
    var s=svg(W,H);
    s.appendChild(el("title",{})).textContent="Median bean temperature, light-leaning versus medium, 400 g";
    for(var v=100;v<=200;v+=20){
      s.appendChild(el("line",{x1:L,y1:Y(v),x2:W-R,y2:Y(v),stroke:C.grid,"stroke-width":1}));
      s.appendChild(text(L-9,Y(v)+3.5,String(v),"svg-lbl","end"));
    }
    s.appendChild(text(L-9,Y(200)-11,"°C","svg-lbl","end"));
    for(var t=0;t<=xmax;t+=120) s.appendChild(text(X(t),H-B+18,mmss(t),"svg-lbl","middle"));

    function line(arr,color,dash){
      var p=arr.map(function(v,i){var t=Math.min(i*step,689);return X(t)+","+Y(v);}).join(" ");
      var o={points:p,fill:"none",stroke:color,"stroke-width":2.4,"stroke-linejoin":"round"};
      if(dash) o["stroke-dasharray"]=dash;
      s.appendChild(el("polyline",o));
    }
    line(med,C.blue); line(clair,C.bt);

    // crack + drop markers
    [[609,189.3,C.bt,"FC 10:09"],[576,187.3,C.blue,"FC 9:36"]].forEach(function(m){
      s.appendChild(el("circle",{cx:X(m[0]),cy:Y(m[1]),r:3.6,fill:m[2],stroke:"#0d0d0c","stroke-width":1.4}));
    });
    s.appendChild(text(X(576)-4,Y(187.3)+18,"first crack","svg-lbl","end"));

    // divergence bracket at the drop
    var xd=X(689);
    s.appendChild(el("line",{x1:xd,y1:Y(195.1),x2:xd,y2:Y(199.7),stroke:C.mark,"stroke-width":2}));
    s.appendChild(el("line",{x1:xd-4,y1:Y(195.1),x2:xd+4,y2:Y(195.1),stroke:C.mark,"stroke-width":2}));
    s.appendChild(el("line",{x1:xd-4,y1:Y(199.7),x2:xd+4,y2:Y(199.7),stroke:C.mark,"stroke-width":2}));
    s.appendChild(text(xd+10,Y(199.7)-2,"+4.6 °C","svg-note"));
    s.appendChild(text(xd+10,Y(199.7)+14,"8 pts Agtron","svg-lbl"));
    s.appendChild(text(xd+10,Y(195.1)+16,"Agtron 64","svg-lbl"));
    s.appendChild(text(xd+10,Y(199.7)-16,"Agtron 56","svg-lbl"));
    s.appendChild(el("line",{x1:L,y1:H-B,x2:W-R,y2:H-B,stroke:C.line,"stroke-width":1}));
    host.appendChild(s);
  })();

  /* ---------- Figure 4 — three templates ---------- */
  (function(){
    var host=document.getElementById("fig-gab"); if(!host) return;
    var W=760,H=320,L=52,R=100,T=24,B=52;
    var stops=["Charge","Mid-dry","Dry end","Mid-Mai","FC","Mid-dev","Drop"];
    var data={
      light:{burner:[80,75,72,62,45,40,40], air:[40,40,40,58,70,78,80], dash:null},
      ml:   {burner:[75,70,60,58,50,45,45], air:[25,25,30,33,35,45,50], dash:"7 4"},
      med:  {burner:[75,75,70,63,50,45,45], air:[30,30,30,35,35,50,55], dash:"1.5 4"}
    };
    var X=function(i){return L+(i/6)*(W-L-R);};
    var Y=function(v){return T+(1-v/100)*(H-T-B);};
    var s=svg(W,H);
    s.appendChild(el("title",{})).textContent="Burner and airflow trajectories for three roast levels";
    for(var v=0;v<=100;v+=25){
      s.appendChild(el("line",{x1:L,y1:Y(v),x2:W-R,y2:Y(v),stroke:C.grid,"stroke-width":1}));
      s.appendChild(text(L-9,Y(v)+3.5,v+"%","svg-lbl","end"));
    }
    stops.forEach(function(nm,i){
      s.appendChild(el("line",{x1:X(i),y1:T,x2:X(i),y2:H-B,stroke:C.grid,"stroke-width":1}));
      var t=text(X(i),H-B+20,nm,"svg-lbl","end");
      t.setAttribute("transform","rotate(-32 "+X(i)+" "+(H-B+20)+")");
      s.appendChild(t);
    });
    ["light","ml","med"].forEach(function(k){
      var d=data[k];
      [["burner",C.ember],["air",C.blue]].forEach(function(pair){
        var p=d[pair[0]].map(function(v,i){return X(i)+","+Y(v);}).join(" ");
        var o={points:p,fill:"none",stroke:pair[1],"stroke-width":k==="light"?2.6:2,
               "stroke-linejoin":"round","opacity":k==="light"?1:.82};
        if(d.dash) o["stroke-dasharray"]=d.dash;
        s.appendChild(el("polyline",o));
      });
    });
    // end labels
    s.appendChild(text(X(6)+9,Y(80)+4,"air 80 · light","svg-note"));
    s.appendChild(text(X(6)+9,Y(55)+4,"air 55 · medium","svg-lbl"));
    s.appendChild(text(X(6)+9,Y(43)+4,"burner ~43","svg-lbl"));
    s.appendChild(el("line",{x1:L,y1:H-B,x2:W-R,y2:H-B,stroke:C.line,"stroke-width":1}));
    host.appendChild(s);
  })();
})();
