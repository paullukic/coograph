/* ================================================================
   Code Graph — graph.js  (Canvas renderer)
   Services → Files (checkbox tree) → Symbols
   ================================================================ */
const Graph = (() => {

  /* ---- Palettes ---- */
  const SVC_COLORS = id => {
    const lo = id.toLowerCase();
    // Frontend groups
    if (lo === "components" || lo === "ui")     return "#3498db";
    if (lo === "hooks")                         return "#e67e22";
    if (lo === "context" || lo === "store" || lo === "state") return "#9b59b6";
    if (lo === "utils" || lo === "helpers" || lo === "lib") return "#1abc9c";
    if (lo === "types" || lo === "constants")   return "#95a5a6";
    if (lo === "styles")                        return "#e91e63";
    if (lo === "api")                           return "#c0392b";
    if (lo === "entity-forms" || lo === "forms") return "#2ecc71";
    if (lo === "i18n" || lo === "messages")     return "#f39c12";
    if (lo.startsWith("("))                     return "#e07b39";  // route groups
    // Backend groups
    if (lo.startsWith("gateway-"))              return "#e07b39";
    if (lo.startsWith("common-") || lo === "common-sdk") return "#9b59b6";
    if (lo.includes("worker"))                  return "#2a9d5c";
    if (lo.startsWith("template-") || lo === "terraform" || lo === "kubernetes") return "#5d7a8a";
    // Features / pages / routes — distinct hues by hash
    const _hash = s => { let h=0; for(let i=0;i<s.length;i++) h=((h<<5)-h)+s.charCodeAt(i); return Math.abs(h); };
    const FEATURE_HUES = ["#4a7fa5","#e07b39","#2a9d5c","#d4b43a","#c0392b","#7b68ee","#16a085","#d35400","#8e44ad","#27ae60"];
    return FEATURE_HUES[_hash(lo) % FEATURE_HUES.length];
  };
  const EXT_COLORS = {
    java:"#4a7fa5",kt:"#7b68ee",scala:"#dc322f",xml:"#e07b39",yaml:"#d4b43a",yml:"#d4b43a",
    sql:"#c0392b",json:"#2a9d5c",py:"#3498db",ts:"#e67e22",tsx:"#e67e22",js:"#f1c40f",jsx:"#f1c40f",
    properties:"#95a5a6",md:"#556",txt:"#556",gradle:"#5a9",
  };
  const fileColor = ext => EXT_COLORS[ext] || "#556";
  const SYM_COLORS = {"class":"#2980b9","interface":"#8e44ad","enum":"#27ae60","function":"#e67e22","method":"#d35400","annotation":"#c0392b","table":"#16a085","endpoint":"#2c3e50"};
  const symColor = kind => SYM_COLORS[kind] || "#556";
  const EDGE_COLORS = {depends_on:"#c8851a",tests_for:"#2a9d5c",inherits:"#e74c3c",implements:"#1abc9c",calls:"#3498db",contains:"#d4b43a"};
  const EDGE_STYLES = {
    depends_on:{w:1.2,dash:null,op:0.55}, tests_for:{w:1.8,dash:[4,3],op:0.55},
    inherits:{w:2.0,dash:null,op:0.65}, implements:{w:1.5,dash:[6,3],op:0.55}, calls:{w:1.0,dash:[3,2],op:0.45}, contains:{w:0.8,dash:[2,2],op:0.25},
  };

  /* ---- Adjacency ---- */
  // Build adjacency from both file-level and symbol-level edges
  const adj = {};
  const _allEdgeSources = [graphData.edges, graphData.symbolEdges];
  for (const src of _allEdgeSources) {
    for (const [kind,list] of Object.entries(src||{})) {
      if (!adj[kind]) adj[kind] = {out:new Map(),in:new Map()};
      for (const e of list) {
        if (!adj[kind].out.has(e.s)) adj[kind].out.set(e.s,[]);
        adj[kind].out.get(e.s).push(e.t);
        if (!adj[kind].in.has(e.t)) adj[kind].in.set(e.t,[]);
        adj[kind].in.get(e.t).push(e.s);
      }
    }
  }
  const svcAdj = {out:new Map(),in:new Map()};
  for (const e of graphData.serviceEdges) {
    const total=(e.depends_on||0)+(e.tests_for||0)+(e.inherits||0)+(e.implements||0)+(e.calls||0);
    if (!svcAdj.out.has(e.s)) svcAdj.out.set(e.s,[]);
    svcAdj.out.get(e.s).push({id:e.t,n:total,...e});
    if (!svcAdj.in.has(e.t)) svcAdj.in.set(e.t,[]);
    svcAdj.in.get(e.t).push({id:e.s,n:total,...e});
  }
  const fileById = new Map();
  for (const files of Object.values(graphData.filesByService)) for (const f of files) fileById.set(f.id,f);
  for (const src of _allEdgeSources) for (const [kind,list] of Object.entries(src||{})) {
    const el=document.getElementById("cnt-"+kind); if(el) el.textContent=list.length.toLocaleString();
  }

  /* ---- Canvas ---- */
  let PANEL_W=340; let W=window.innerWidth-PANEL_W, H=window.innerHeight;
  const canvas=document.getElementById("graph"), ctx=canvas.getContext("2d"), dpr=window.devicePixelRatio||1;
  function resizeCanvas(){W=window.innerWidth-PANEL_W;H=window.innerHeight;canvas.width=W*dpr;canvas.height=H*dpr;canvas.style.width=W+"px";canvas.style.height=H+"px";canvas.style.marginLeft=PANEL_W+"px";}
  resizeCanvas();

  /* ---- Zoom ---- */
  let transform=d3.zoomIdentity;
  const zoomBehavior=d3.zoom().scaleExtent([0.02,30]).on("zoom",e=>{transform=e.transform;draw();});
  const canvasSel=d3.select(canvas); canvasSel.call(zoomBehavior); canvasSel.on("dblclick.zoom",null);
  window.addEventListener("resize",()=>{resizeCanvas();draw();});

  /* ---- Panel resize ---- */
  (function(){
    const handle=document.getElementById("panel-resize"),panel=document.getElementById("panel");if(!handle||!panel)return;
    handle.addEventListener("mousedown",e=>{e.preventDefault();e.stopPropagation();handle.classList.add("active");
      function onMove(me){me.preventDefault();PANEL_W=Math.max(200,Math.min(600,me.clientX));panel.style.width=PANEL_W+"px";resizeCanvas();draw();}
      function onUp(){handle.classList.remove("active");window.removeEventListener("mousemove",onMove);window.removeEventListener("mouseup",onUp);
        canvasSel.call(zoomBehavior);canvasSel.on("dblclick.zoom",null);
      }
      window.addEventListener("mousemove",onMove);window.addEventListener("mouseup",onUp);
    });
  })();

  /* ---- State ---- */
  let view="services",selectedId=null,hoveredId=null,sim=null,curNodes=[],curEdges=[],connSet=null;
  let _animFrame=null,_searchQ="";
  const NODE_CAP=2500;
  let _allSvcFiles=[],_allSvcFileIds=new Set(),_connCount=new Map(),_maxConn=1,_currentSvcName="";
  let _excludeTests=true,_excludePomSpec=true;
  let _activeSymTypes=new Set();
  let _lastSelectedFileIds=new Set();
  const $=id=>document.getElementById(id);

  /* ---- Quadtree ---- */
  let qt=null;
  function rebuildQuadtree(){qt=curNodes.length?d3.quadtree().x(d=>d.x).y(d=>d.y).addAll(curNodes):null;}
  function findNode(sx,sy){
    if(!qt)return null;const[gx,gy]=transform.invert([sx,sy]);let best=null,bd=Infinity;
    qt.visit((node,x0,y0,x1,y1)=>{if(!node.length){let n=node;do{const d=n.data,r=d._r||8,dist=Math.hypot(gx-d.x,gy-d.y);if(dist<r+5&&dist<bd){bd=dist;best=d;}}while(n=n.next);}const hw=(x1-x0)/2;return Math.hypot(Math.max(0,Math.abs(gx-(x0+x1)/2)-hw),Math.max(0,Math.abs(gy-(y0+y1)/2)-hw))>bd;});
    return best;
  }

  /* ---- Helpers ---- */
  const maxFiles=Math.max(...graphData.services.map(s=>s.files));
  const svcR=d=>6+Math.sqrt(d.files/maxFiles)*28;
  function stopSim(){if(_animFrame){cancelAnimationFrame(_animFrame);_animFrame=null;}if(sim){sim.stop();sim=null;}}
  function setStats(t){$("stats").textContent=t;}
  function nodeMap(){return new Map(curNodes.map(n=>[n.id,n]));}
  function activeTypes(){return[...document.querySelectorAll("[data-etype]")].filter(cb=>cb.checked).map(cb=>cb.dataset.etype);}

  /* ---- Draw ---- */
  function draw(){
    ctx.save();ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,H);
    ctx.translate(transform.x,transform.y);ctx.scale(transform.k,transform.k);
    const k=transform.k;
    // Re-resolve edge refs (nodes may have moved)
    _resolveEdgeRefs();
    // Edges
    for(const e of curEdges){const sn=e._sn,tn=e._tn;if(!sn||!tn)continue;const st=EDGE_STYLES[e.kind]||{};ctx.beginPath();ctx.moveTo(sn.x,sn.y);ctx.lineTo(tn.x,tn.y);ctx.strokeStyle=EDGE_COLORS[e.kind]||"#666";ctx.globalAlpha=e._op??st.op??0.5;ctx.lineWidth=(st.w||1)/Math.max(k,0.3);ctx.setLineDash(st.dash?st.dash.map(v=>v/Math.max(k,0.3)):[]);ctx.stroke();}
    ctx.setLineDash([]);ctx.globalAlpha=1;
    // Edge labels (only when a node is selected)
    if(selectedId&&k>0.4){
      const elFs=Math.min(10,Math.max(6,8/Math.sqrt(k)));
      ctx.font=`${elFs}px -apple-system,sans-serif`;ctx.textAlign="center";ctx.textBaseline="middle";
      const shortKind={depends_on:"dep",tests_for:"test",inherits:"ext",implements:"impl",calls:"call",contains:"has"};
      for(const e of curEdges){const sn=e._sn,tn=e._tn;if(!sn||!tn)continue;if(e._op&&e._op<0.3)continue;
        const mx=(sn.x+tn.x)/2,my=(sn.y+tn.y)/2;
        ctx.globalAlpha=0.8;ctx.strokeStyle="#0f1117";ctx.lineWidth=2.5;ctx.lineJoin="round";
        ctx.strokeText(shortKind[e.kind]||e.kind,mx,my);
        ctx.fillStyle=EDGE_COLORS[e.kind]||"#888";ctx.fillText(shortKind[e.kind]||e.kind,mx,my);
      }
      ctx.globalAlpha=1;
    }
    // Nodes
    for(const d of curNodes){const r=d._r||8,op=_nodeOp(d);if(op<0.02)continue;ctx.globalAlpha=op;ctx.beginPath();ctx.arc(d.x||0,d.y||0,r,0,Math.PI*2);
      if(d._external){ctx.fillStyle="#1a1d2a";ctx.fill();ctx.setLineDash([3/Math.max(k,0.3),2/Math.max(k,0.3)]);ctx.strokeStyle="#fff";ctx.lineWidth=1.5/Math.max(k,0.3);ctx.stroke();ctx.setLineDash([]);}
      else{
        ctx.fillStyle=d._color||"#4a7fa5";ctx.fill();
        if(d.id===selectedId){
          ctx.save();ctx.globalAlpha=0.3;ctx.beginPath();ctx.arc(d.x,d.y,r+8/Math.max(k,0.3),0,Math.PI*2);ctx.fillStyle="#fff";ctx.fill();ctx.restore();
          ctx.beginPath();ctx.arc(d.x,d.y,r,0,Math.PI*2);ctx.strokeStyle="#fff";ctx.lineWidth=3/Math.max(k,0.3);ctx.stroke();
          ctx.beginPath();ctx.arc(d.x,d.y,r,0,Math.PI*2);ctx.fillStyle=d._color||"#4a7fa5";ctx.fill();
        } else {
          ctx.strokeStyle=d.id===hoveredId?"#fff8":"rgba(0,0,0,0.4)";ctx.lineWidth=(d.id===hoveredId?1.5:0.6)/Math.max(k,0.3);ctx.stroke();
        }
      }
      // Inline label for selected, connected, external, hovered nodes
      const _forceLabel=d.id===selectedId||(connSet&&connSet.has(d.id))||d._external||d.id===hoveredId;
      if(_forceLabel){
        const _fs=Math.min(11,Math.max(6,9/Math.sqrt(Math.max(k,0.3))));
        ctx.save();ctx.globalAlpha=1;ctx.font=_fs+"px -apple-system,sans-serif";ctx.textAlign="start";ctx.textBaseline="middle";
        ctx.strokeStyle="#0f1117";ctx.lineWidth=3;ctx.lineJoin="round";
        const _lbl=d._external?(d.label||"")+" ("+d._svc+")":(d.label||d.name||"");
        if(_lbl){ctx.strokeText(_lbl,d.x+r+4,d.y);ctx.fillStyle=d.id===selectedId?"#fff":d._external?"#e67e22":"#ccc";ctx.fillText(_lbl,d.x+r+4,d.y);}
        ctx.restore();
      }
    }
    _drawLabels(k);ctx.restore();
  }
  function _nodeOp(d){if(_searchQ){const t=(d.label||d.name||d.file||"").toLowerCase();if(!t.includes(_searchQ))return 0.06;}return 1;}
  function _drawLabels(k){
    const hasSel=!!selectedId;
    let showAll;
    if(view==="services"){if(k<0.3)return;showAll=true;}
    else if(view.startsWith("files:")){if(k<0.7&&!hasSel)return;showAll=k>1.5;}
    else{if(k<0.4)return;showAll=true;}
    const fs=Math.min(14,Math.max(7,10/Math.sqrt(Math.max(k,0.3))));
    ctx.font=`${fs}px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif`;ctx.textBaseline="middle";

    for(const d of curNodes){
      const op=_nodeOp(d);if(op<0.1)continue;
      const isSel=d.id===selectedId;
      const connected=!!(hasSel&&connSet&&connSet.has(d.id));
      const isExt=d._external===true;
      const forceLabel=isSel||connected||isExt||d.id===hoveredId;

      // Skip non-forced labels when not showing all
      if(!forceLabel&&!showAll&&(d._conns||0)<3)continue;

      const r=d._r||8;
      // For external nodes: show "FileName (service)"
      const label=isExt?(d.label||"")+" ("+d._svc+")":(d.label||d.name||"");
      if(!label)continue;

      ctx.globalAlpha=forceLabel?1:op*0.9;
      ctx.textAlign=view==="services"?"center":"start";
      ctx.strokeStyle="#0f1117";ctx.lineWidth=isSel?4:3.5;ctx.lineJoin="round";

      const lx=view==="services"?d.x:d.x+r+3;
      const ly=view==="services"?d.y+r+fs/2+4:d.y;

      ctx.strokeText(label,lx,ly);
      ctx.fillStyle=isSel?"#fff":isExt?"#e67e22":view==="services"?"#ccc":"#bbb";
      ctx.fillText(label,lx,ly);
    }
    ctx.globalAlpha=1;
  }

  /* ---- Simulation ---- */
  function runSimulation(s,onTick){
    sim=s;s.stop();const n=curNodes.length;
    if(n<600){const iters=Math.ceil(Math.log(s.alphaMin())/Math.log(1-s.alphaDecay()));for(let i=0;i<iters;i++)s.tick();rebuildQuadtree();if(onTick)onTick();draw();s.on("tick",()=>{rebuildQuadtree();draw();}).alpha(0).restart().stop();}
    else{const tpf=n>1000?3:5;(function step(){for(let i=0;i<tpf;i++)s.tick();rebuildQuadtree();if(onTick)onTick();draw();if(s.alpha()>s.alphaMin())_animFrame=requestAnimationFrame(step);else{_animFrame=null;s.on("tick",()=>{rebuildQuadtree();draw();}).alpha(0).restart().stop();}})();}
  }

  /* ---- Drag (capture mousedown on node, block zoom) ---- */
  let _dragNode=null,_isDragging=false,_mouseDownPos=null;
  canvas.addEventListener("mousedown",e=>{
    if(e.button!==0)return;const node=findNode(e.offsetX,e.offsetY);if(!node)return;
    e.stopPropagation();e.preventDefault();
    _dragNode=node;_mouseDownPos={x:e.clientX,y:e.clientY};
    const[gx,gy]=transform.invert([e.offsetX,e.offsetY]);_dragNode.fx=gx;_dragNode.fy=gy;
    function onMove(me){
      if(!_isDragging&&Math.hypot(me.clientX-_mouseDownPos.x,me.clientY-_mouseDownPos.y)>5){_isDragging=true;if(sim)sim.alphaTarget(0.3).restart();}
      if(!_isDragging)return;
      const rect=canvas.getBoundingClientRect();const[mx,my]=transform.invert([me.clientX-rect.left,me.clientY-rect.top]);
      _dragNode.fx=mx;_dragNode.fy=my;rebuildQuadtree();_resolveEdgeRefs();draw();
    }
    function onUp(ue){
      window.removeEventListener("mousemove",onMove);window.removeEventListener("mouseup",onUp);
      if(sim)sim.alphaTarget(0);if(_dragNode){_dragNode.fx=null;_dragNode.fy=null;}
      if(!_isDragging)_handleClick(ue);
      _dragNode=null;_mouseDownPos=null;setTimeout(()=>{_isDragging=false;},0);
    }
    window.addEventListener("mousemove",onMove);window.addEventListener("mouseup",onUp);
  },true);

  /* ---- Hover ---- */
  const tip=$("tooltip");
  function showTip(e,title,sub,extra){tip.style.display="block";$("tt-title").textContent=title;$("tt-sub").textContent=sub||"";$("tt-extra").textContent=extra||"";tip.style.left=Math.min(e.offsetX+14+PANEL_W,window.innerWidth-370)+"px";tip.style.top=(e.offsetY-10)+"px";}
  function hideTip(){tip.style.display="none";}
  canvas.addEventListener("mousemove",e=>{
    if(_isDragging||_dragNode)return;
    const node=findNode(e.offsetX,e.offsetY);const prev=hoveredId;hoveredId=node?node.id:null;if(hoveredId!==prev)draw();
    if(node){canvas.style.cursor="pointer";
      if(view==="services")showTip(e,node.label,node.files.toLocaleString()+" files",node.classes+" cls · "+node.functions+" fn");
      else if(view.startsWith("files:")){const svcTag=node._external?" ["+node._svc+"]":"";showTip(e,node.label+svcTag,node.file,(node._conns?node._conns+" conn":"")+(((graphData.symbolsByFile[node.id]||[]).length)?" · "+(graphData.symbolsByFile[node.id]||[]).length+" symbols":""));}
      else showTip(e,node.name||node.label,node.kind||"",node.line?"Line "+node.line:"");
    }else{canvas.style.cursor="default";hideTip();}
  });

  /* ---- Click ---- */
  let _lastClickTime=0,_lastClickNodeId=null,_clickTimer=null;
  function _handleClick(e){
    const rect=canvas.getBoundingClientRect(),ox=e.clientX-rect.left,oy=e.clientY-rect.top;
    const node=findNode(ox,oy),now=Date.now();
    if(node&&_lastClickNodeId===node.id&&(now-_lastClickTime)<400){_lastClickTime=0;_lastClickNodeId=null;if(_clickTimer){clearTimeout(_clickTimer);_clickTimer=null;}_doDrill(node);return;}
    _lastClickTime=now;_lastClickNodeId=node?node.id:null;if(_clickTimer){clearTimeout(_clickTimer);_clickTimer=null;}
    if(!node){deselect();return;}
    const cap=node;_clickTimer=setTimeout(()=>{_clickTimer=null;_doSelect(cap);},300);
  }
  canvas.addEventListener("click",e=>{if(_isDragging)return;const node=findNode(e.offsetX,e.offsetY);if(!node)deselect();});

  function _doDrill(node){
    if(view==="services")renderFileView(node.id);
    else if(view.startsWith("files:")&&(graphData.symbolsByFile[node.id]||[]).length)renderSymbolView(node.id,node.label);
  }
  function _doSelect(node){
    if(view==="services")selectService(node);
    else if(view.startsWith("files:"))selectFile(node);
    else if(view.startsWith("symbols:"))selectSymbol(node);
  }

  /* ---- Edges ---- */
  function _resolveEdgeRefs(){const nm=nodeMap();for(const e of curEdges){e._sn=nm.get(e.s)||null;e._tn=nm.get(e.t)||null;}}
  function computeEdgesForNode(d){const nm=nodeMap(),types=activeTypes(),lines=[];for(const kind of types){for(const t of(adj[kind]?.out.get(d.id)||[]))if(nm.has(t))lines.push({s:d.id,t,kind});for(const s of(adj[kind]?.in.get(d.id)||[]))if(nm.has(s))lines.push({s,t:d.id,kind});}curEdges=lines;_resolveEdgeRefs();return lines;}
  function computeAllEdgesInView(op){const nm=nodeMap(),types=activeTypes(),lines=[];for(const kind of types)for(const src of _allEdgeSources)for(const e of(src[kind]||[]))if(nm.has(e.s)&&nm.has(e.t))lines.push({s:e.s,t:e.t,kind,_op:op});curEdges=lines;_resolveEdgeRefs();}
  function clearEdges(){curEdges=[];}

  /* ---- Deselect ---- */
  function deselect(){selectedId=null;connSet=null;Panel.hideNodeInfo();Panel.highlightNodeListItem(null);
    // Remove external nodes
    curNodes=curNodes.filter(n=>!n._external);rebuildQuadtree();
    if($("show-all-cb")?.checked)computeAllEdgesInView(0.3);
    else if(view.startsWith("files:"))_showDefaultEdges();
    else clearEdges();
    draw();}

  /* ---- Pan ---- */
  function panToNode(d){const s=2.5;canvasSel.transition().duration(500).call(zoomBehavior.transform,d3.zoomIdentity.translate(W/2-d.x*s,H/2-d.y*s).scale(s));}
  function panToNeighborhood(d,ids){
    const ns=curNodes.filter(n=>ids.has(n.id));if(!ns.length)return;
    const cx=ns.reduce((s,n)=>s+n.x,0)/ns.length,cy=ns.reduce((s,n)=>s+n.y,0)/ns.length;
    const spread=Math.max(...ns.map(n=>Math.hypot(n.x-cx,n.y-cy)),100);
    const scale=Math.min(Math.max(Math.min(W,H)/(spread*3),0.3),3);
    canvasSel.transition().duration(500).call(zoomBehavior.transform,d3.zoomIdentity.translate(W/2-cx*scale,H/2-cy*scale).scale(scale));
  }

  /* ---- Panel helper ---- */
  function _setPanel(o){
    const s=(id,show,dv)=>{const el=$(id);if(el)el.style.display=show?(dv||""):"none";};
    $("crumb-text").textContent=o.crumb;$("back-btn").style.display=o.back?"inline-block":"none";
    s("show-all-row",o.showAll);if(o.showAll){const cb=$("show-all-cb");if(cb)cb.checked=false;}
    s("file-legend",o.fileLegend);s("sym-legend",o.symLegend);s("svc-legend",o.svcLegend);
    s("ext-filters",o.extFilters,"flex");s("ext-title",o.extFilters);
    s("sym-type-filters",o.symTypeFilters);s("exclude-tests-row",o.excludeTests);
    $("search").value="";_searchQ="";$("search").placeholder=o.search||"Search…";
  }

  /* ---- Exclude filters ---- */
  function _resetExcludes(){
    _excludeTests=true;_excludePomSpec=true;
    const c1=$("exclude-tests-cb");if(c1)c1.checked=true;
    const c2=$("exclude-pomspec-cb");if(c2)c2.checked=true;
  }
  function onExcludeTestsChange(){_excludeTests=$("exclude-tests-cb")?.checked??false;if(view.startsWith("files:")&&_lastSelectedFileIds.size>0)_rebuildFileView();}
  function onExcludePomSpecChange(){_excludePomSpec=$("exclude-pomspec-cb")?.checked??false;if(view.startsWith("files:")&&_lastSelectedFileIds.size>0)_rebuildFileView();}

  /* ---- Sym type filters ---- */
  function _resetSymTypes(){document.querySelectorAll(".sym-type-cb").forEach(cb=>{cb.checked=false;});_activeSymTypes=new Set();}
  function onSymTypeChange(){_activeSymTypes=new Set();document.querySelectorAll(".sym-type-cb:checked").forEach(cb=>_activeSymTypes.add(cb.dataset.symtype));if(view.startsWith("files:")&&_lastSelectedFileIds.size>0)_rebuildFileView();}

  /* ==============================================================
     SERVICE VIEW
     ============================================================== */
  function renderServiceView(){
    view="services";selectedId=null;connSet=null;stopSim();curEdges=[];
    curNodes=graphData.services.map(s=>({...s,_r:svcR(s),_color:SVC_COLORS(s.id)}));
    _setPanel({crumb:"Services",back:false,showAll:false,fileLegend:false,symLegend:false,svcLegend:true,extFilters:false,symTypeFilters:false,excludeTests:false,search:"Search services…"});
    Panel.hideNodeInfo();
    const totalEdges=graphData.serviceEdges.reduce((a,e)=>a+(e.depends_on||0)+(e.tests_for||0)+(e.inherits||0)+(e.implements||0)+(e.calls||0),0);
    setStats(curNodes.length+" services · "+graphData.totalFiles.toLocaleString()+" files · "+graphData.totalSymbols.toLocaleString()+" symbols · "+totalEdges.toLocaleString()+" cross-svc edges");
    runSimulation(d3.forceSimulation(curNodes).force("charge",d3.forceManyBody().strength(-800)).force("center",d3.forceCenter(W/2,H/2)).force("collision",d3.forceCollide(d=>d._r+30)).force("link",d3.forceLink(graphData.serviceEdges.map(e=>({source:e.s,target:e.t}))).id(d=>d.id).distance(200).strength(0.1)).alphaDecay(0.025));
    Panel.buildNodeList(curNodes,{colorFn:d=>d._color,labelFn:d=>d.label,subFn:d=>d.files+" files, "+d.classes+" cls, "+d.functions+" fn",onClickFn:d=>{panToNode(d);selectService(d);}});
  }
  function selectService(d){
    selectedId=d.id;const outE=svcAdj.out.get(d.id)||[],inE=svcAdj.in.get(d.id)||[];
    connSet=new Set([d.id,...outE.map(e=>e.id),...inE.map(e=>e.id)]);
    curEdges=[...outE.map(e=>({s:d.id,t:e.id,kind:"depends_on"})),...inE.map(e=>({s:e.id,t:d.id,kind:"depends_on"}))];
    _resolveEdgeRefs();draw();
    Panel.showNodeInfo(d.label,d.files.toLocaleString()+" files · "+d.classes+" cls · "+d.functions+" fn");
    Panel.showServiceConnections(d);Panel.highlightNodeListItem(d.id);
  }

  /* ==============================================================
     FILE VIEW — checkbox tree + filters
     ============================================================== */
  function renderFileView(svcName){
    view="files:"+svcName;selectedId=null;connSet=null;_currentSvcName=svcName;stopSim();curEdges=[];
    _allSvcFiles=graphData.filesByService[svcName]||[];
    _allSvcFileIds=new Set(_allSvcFiles.map(f=>f.id));
    _connCount=new Map();
    for(const[kind,list]of Object.entries(graphData.edges))for(const e of list)if(_allSvcFileIds.has(e.s)&&_allSvcFileIds.has(e.t)){_connCount.set(e.s,(_connCount.get(e.s)||0)+1);_connCount.set(e.t,(_connCount.get(e.t)||0)+1);}
    _maxConn=Math.max(1,...(_connCount.size?_connCount.values():[1]));
    _activeSymTypes=new Set();_lastSelectedFileIds=new Set();curNodes=[];
    _setPanel({crumb:svcName,back:true,showAll:true,fileLegend:true,symLegend:false,svcLegend:false,extFilters:true,symTypeFilters:true,excludeTests:true,search:"Search files…"});
    Panel.hideNodeInfo();Panel.buildExtFilters();_resetSymTypes();_resetExcludes();
    setStats(_allSvcFiles.length.toLocaleString()+" files · check folders in panel to visualize");draw();
    Panel.buildCheckboxTree(_allSvcFiles,{colorFn:d=>fileColor(d.ext),labelFn:d=>d.label,pathFn:d=>d.file,
      onClickFn:d=>{
        // Find the actual node in curNodes (has x/y from simulation)
        const n=curNodes.find(c=>c.id===d.id);
        if(n){panToNode(n);selectFile(n);}
        else{/* node not on graph — just show info */Panel.showNodeInfo(d.label,d.file);Panel.showSymbolList(d.id);}
      },
      onCheckChange:ids=>{_lastSelectedFileIds=ids;_rebuildFileView();}});
  }

  const _isTest=f=>/[/\\](test|tests|__tests__|spec)[/\\]/i.test(f.file)||/[Tt]est\./i.test(f.label);
  const _isJunk=f=>/pom\.xml$/i.test(f.file)||/[/\\]specs?[/\\]/i.test(f.file)||/package-info\.java$/i.test(f.file);

  function _rebuildFileView(){
    const sel=_lastSelectedFileIds;const prevSelected=selectedId;const prevConnSet=connSet;
    // Save positions of existing nodes
    const oldPos=new Map();for(const n of curNodes)if(n.x!=null)oldPos.set(n.id,{x:n.x,y:n.y});
    stopSim();curEdges=[];
    if(sel.size>NODE_CAP){curNodes=[];selectedId=null;connSet=null;setStats("Too many ("+sel.size.toLocaleString()+"). Max "+NODE_CAP+" — uncheck some folders.");draw();return;}
    // File nodes
    const activeExts=Panel.getActiveExts();const hasExtFilter=activeExts.size>0&&activeExts.size<graphData.topExts.length;
    const fileNodes=_allSvcFiles.filter(f=>{if(!sel.has(f.id))return false;if(_excludeTests&&_isTest(f))return false;if(_excludePomSpec&&_isJunk(f))return false;if(hasExtFilter&&!activeExts.has(f.ext))return false;return true;}).map(f=>{
      const cc=_connCount.get(f.id)||0,syms=graphData.symbolsByFile[f.id]||[];
      let color=fileColor(f.ext);const pr=syms.find(s=>s.kind==="class"||s.kind==="interface"||s.kind==="enum");
      if(pr)color=symColor(pr.kind);
      const node={...f,_r:3+Math.sqrt(cc/_maxConn)*8,_conns:cc,_color:color};
      // Restore position if node existed before
      const op=oldPos.get(f.id);if(op){node.x=op.x;node.y=op.y;}
      return node;
    });
    // Symbol overlay nodes
    const symNodes=[];
    if(_activeSymTypes.size>0)for(const f of fileNodes)for(const s of(graphData.symbolsByFile[f.id]||[]))if(_activeSymTypes.has(s.kind)){const sn={...s,label:s.name,file:f.file,_r:s.kind==="class"||s.kind==="interface"?6:s.kind==="enum"?5:4,_color:symColor(s.kind),_parentFileId:f.id};const op=oldPos.get(s.id);if(op){sn.x=op.x;sn.y=op.y;}symNodes.push(sn);}
    curNodes=[...fileNodes,...symNodes];
    if(!curNodes.length){selectedId=null;connSet=null;setStats(_allSvcFiles.length.toLocaleString()+" files · check folders in panel to visualize");draw();return;}
    const visibleIds=new Set(curNodes.map(n=>n.id));
    const parts=[fileNodes.length+" files"];if(symNodes.length)parts.push(symNodes.length+" symbols");
    setStats(parts.join(" · ")+" / "+_allSvcFiles.length.toLocaleString()+" total");
    // Links
    const linkData=[];
    for(const[kind,list]of Object.entries(graphData.edges))for(const e of list)if(visibleIds.has(e.s)&&visibleIds.has(e.t))linkData.push({source:e.s,target:e.t});
    for(const s of symNodes)if(visibleIds.has(s._parentFileId))linkData.push({source:s._parentFileId,target:s.id});
    const n=curNodes.length,ed=n>0?linkData.length/n:0,dm=Math.max(1,1+Math.log2(1+ed)*0.4);
    const charge=-(n>500?50:n>200?80:120)*dm,ld=(n>500?50:n>200?70:100)*dm,ls=(n>500?0.03:n>200?0.05:0.08)/dm;
    const collide=n>500?18:n>200?25:35;
    // Use gentle alpha if most nodes have positions (incremental update), full alpha for fresh layout
    const hasPositions=curNodes.filter(n=>n.x!=null).length>curNodes.length*0.5;
    const s=d3.forceSimulation(curNodes).force("charge",d3.forceManyBody().strength(charge)).force("center",d3.forceCenter(W/2,H/2)).force("collision",d3.forceCollide(d=>d._r+collide)).force("link",d3.forceLink(linkData).id(d=>d.id).distance(ld).strength(ls)).alphaDecay(0.028);
    if(hasPositions)s.alpha(0.15); // gentle settle — don't blow apart existing layout
    runSimulation(s);
    // Restore selection if node survived rebuild — re-run selectFile on it
    if(prevSelected){
      const restored=curNodes.find(n=>n.id===prevSelected);
      if(restored) setTimeout(()=>selectFile(restored),150);
      else{selectedId=null;connSet=null;Panel.hideNodeInfo();}
    }else{selectedId=null;connSet=null;}
    // Always show edges at low opacity
    _showDefaultEdges();
  }

  /** Show all active edge types at low opacity by default */
  function _showDefaultEdges(){
    if(selectedId){/* edges already set by selection */return;}
    const nm=nodeMap(),types=activeTypes(),lines=[];
    for(const kind of types)
      for(const src of _allEdgeSources)
        for(const e of(src[kind]||[]))
          if(nm.has(e.s)&&nm.has(e.t))lines.push({s:e.s,t:e.t,kind,_op:0.15});
    curEdges=lines;_resolveEdgeRefs();
  }

  function selectFile(d){
    // External node click — just show info, don't rebuild graph
    if(d._external){
      selectedId=d.id;draw();
      Panel.showNodeInfo(d.label+" ["+d._svc+"]",d.file);
      Panel.showSymbolList(d.id);
      return;
    }
    selectedId=d.id;
    // Remove previous external nodes
    curNodes=curNodes.filter(n=>!n._external);
    // Find ALL connected files (including cross-service)
    const types=activeTypes(),allConnIds=new Set();
    for(const kind of types){
      for(const t of(adj[kind]?.out.get(d.id)||[]))allConnIds.add(t);
      for(const s of(adj[kind]?.in.get(d.id)||[]))allConnIds.add(s);
    }
    // Add external nodes for cross-service connections not already visible
    const nm=nodeMap();
    for(const cid of allConnIds){
      if(nm.has(cid))continue;
      const f=fileById.get(cid);if(!f)continue;
      const svc=f.file.split("/")[0];
      curNodes.push({...f,_r:5,_color:"#fff",_external:true,_svc:svc,
        x:d.x+(Math.random()-0.5)*100,y:d.y+(Math.random()-0.5)*100});
    }
    rebuildQuadtree();
    // Update simulation with new node set so externals participate in forces
    if(sim){sim.nodes(curNodes);sim.alpha(0.1).restart();}
    // Now compute edges with the expanded node set
    const lines=computeEdgesForNode(d);
    connSet=new Set([d.id,...lines.map(e=>e.s),...lines.map(e=>e.t)]);
    draw();_pullNeighbors(d,connSet);
    Panel.showNodeInfo(d.label,d.file);Panel.showFileConnections(d);Panel.showSymbolList(d.id);Panel.revealAndHighlight(d.id);
  }

  function _pullNeighbors(center,ids){
    if(ids.size<2){panToNode(center);return;}
    const neighbors=curNodes.filter(n=>ids.has(n.id)&&n.id!==center.id);
    if(!neighbors.length){panToNode(center);return;}
    const nc=neighbors.length,starts=neighbors.map(n=>({n,sx:n.x,sy:n.y}));
    const avgR=neighbors.reduce((s,n)=>s+(n._r||6),0)/nc;
    const perNode=avgR*2+25,ringR=Math.max(50,(nc*perNode)/(2*Math.PI));
    const targets=starts.map((_,i)=>{const a=(i/nc)*Math.PI*2-Math.PI/2;return{tx:center.x+Math.cos(a)*ringR,ty:center.y+Math.sin(a)*ringR};});
    let step=0;const steps=15;
    (function anim(){step++;const t=Math.min(step/steps,1),ease=t*(2-t);
      for(let i=0;i<starts.length;i++){starts[i].n.x=starts[i].sx+(targets[i].tx-starts[i].sx)*ease;starts[i].n.y=starts[i].sy+(targets[i].ty-starts[i].sy)*ease;}
      rebuildQuadtree();_resolveEdgeRefs();draw();
      if(step<steps)requestAnimationFrame(anim);
      else{
        // Rebuild simulation WITHOUT forceCenter so nodes stay where pulled
        const n=curNodes.length;
        const collide=n>500?18:n>200?25:35;
        sim=d3.forceSimulation(curNodes)
          .force("collision",d3.forceCollide(d=>d._r+collide))
          .force("charge",d3.forceManyBody().strength(-30))
          .alphaDecay(0.05).alpha(0).restart().stop();
        sim.on("tick",()=>{rebuildQuadtree();_resolveEdgeRefs();draw();});
        panToNeighborhood(center,ids);
      }
    })();
  }

  /* ==============================================================
     SYMBOL VIEW
     ============================================================== */
  function renderSymbolView(fileId,fileName){
    const syms=graphData.symbolsByFile[fileId]||[];if(!syms.length)return;
    view="symbols:"+fileId;selectedId=null;connSet=null;stopSim();curEdges=[];curNodes=[];
    // Reset zoom to identity so symbols render centered
    transform=d3.zoomIdentity;
    zoomBehavior.on("zoom",null);canvasSel.call(zoomBehavior.transform,d3.zoomIdentity);
    zoomBehavior.on("zoom",e=>{transform=e.transform;draw();});
    curNodes=syms.map(s=>({...s,label:s.name,_r:(s.kind==="class"||s.kind==="interface")?8:s.kind==="enum"?7:s.kind==="annotation"?6:5,_color:symColor(s.kind)}));
    _setPanel({crumb:fileName,back:true,showAll:false,fileLegend:false,symLegend:true,svcLegend:false,extFilters:false,symTypeFilters:false,excludeTests:false,search:"Search symbols…"});
    Panel.hideNodeInfo();setStats(curNodes.length+" symbols in "+fileName);
    const nm=nodeMap();curEdges=[];for(const[kind,elist]of Object.entries(graphData.symbolEdges))for(const e of elist)if(nm.has(e.s)&&nm.has(e.t))curEdges.push({s:e.s,t:e.t,kind});
    runSimulation(d3.forceSimulation(curNodes).force("charge",d3.forceManyBody().strength(-180)).force("center",d3.forceCenter(W/2,H/2)).force("collision",d3.forceCollide(d=>d._r+14)).alphaDecay(0.04),()=>_resolveEdgeRefs());
    Panel.buildNodeList(curNodes,{colorFn:d=>d._color,labelFn:d=>d.name,subFn:d=>d.kind+(d.line?" — line "+d.line:""),onClickFn:d=>{panToNode(d);selectSymbol(d);}});
  }
  function selectSymbol(d){selectedId=d.id;connSet=null;draw();Panel.showNodeInfo(d.name,d.kind+" · Line "+(d.line||"?"));Panel.highlightNodeListItem(d.id);}

  /* ---- Panel callbacks ---- */
  function onEdgeFilterChange(){
    if(!selectedId){
      if($("show-all-cb")?.checked)computeAllEdgesInView(0.3);else clearEdges();
    }else{
      // Just recompute edges for the selected node — don't re-run selectFile
      const d=curNodes.find(n=>n.id===selectedId);
      if(d){computeEdgesForNode(d);connSet=new Set([d.id,...curEdges.map(e=>e.s),...curEdges.map(e=>e.t)]);}
    }
    draw();
  }
  function filterCurrentView(){if(view.startsWith("files:")&&_lastSelectedFileIds.size>0)_rebuildFileView();else draw();}
  function applySearch(q){_searchQ=q;draw();}
  function drawAllEdgesInView(){computeAllEdgesInView(0.3);draw();}

  /* ---- Public API ---- */
  return{
    get view(){return view;},get curNodes(){return curNodes;},adj,svcAdj,fileById,
    renderServiceView,renderFileView,renderSymbolView,selectService,selectFile,
    activeTypes,drawAllEdgesInView,clearEdges:()=>{clearEdges();draw();},deselect,
    onEdgeFilterChange,filterCurrentView,applySearch,panToNode,
    onSymTypeChange,onExcludeTestsChange,onExcludePomSpecChange,
    svcColor:SVC_COLORS,
  };
})();
Panel.buildExtFilters();
// Build dynamic service/group legend from actual data
(function(){
  const el=document.getElementById("svc-legend-items");if(!el)return;
  const svcs=graphData.services.sort((a,b)=>b.files-a.files);
  for(const s of svcs){
    const row=document.createElement("div");row.className="filter-row";
    row.innerHTML='<span class="dot-swatch" style="background:'+Graph.svcColor(s.id)+'"></span><span class="filter-label">'+s.label+' <span style="color:#445;font-size:10px">('+s.files+')</span></span>';
    el.appendChild(row);
  }
})();
Graph.renderServiceView();
