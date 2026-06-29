// inject.js — iframe popup (no auto-close), outside-click to close, Shift to open (scoped to #qa)
// + Nút tròn "＋" mở panel Add-to-DB dạng modal (center screen, big)
// + Hotkey Ctrl+Shift+A: mở panel Add từ selection hiện tại
(function () {
  // cleanup cũ nếu có
  if (window.__hanziMiniCleanup) { try { window.__hanziMiniCleanup(); } catch (e) {} }

  const root = document.getElementById('qa');
  if (!root || root.__hanziMiniInjected) return;
  root.__hanziMiniInjected = true;
  // Kill mouse-focus ring; keep keyboard focus ring
const __focusCSS = document.createElement('style');
__focusCSS.textContent = `
  #hanzi-mini-iframe button { outline: none; box-shadow: none; }
  #hanzi-mini-iframe button:focus { outline: none; box-shadow: none; }
  /* Hiện outline khi focus bằng bàn phím */
  #hanzi-mini-iframe button:focus-visible {
    outline: 2px solid #c79f73;
    outline-offset: 2px;
  }
`;
document.head.appendChild(__focusCSS);


  // Listen for requests from iframe to lookup a sub-component
  window.addEventListener('message', function(ev){
    try{
      var data = ev.data || {};
      if(data && data.type === 'yomi-nav'){
        if(data.dir < 0) __goBack();
        else __goFwd();
        return;
      }
      if(data && data.type === 'yomi-hello'){
        __updateNavButtons();
        return;
      }
      if(data && data.type === 'yomi-close'){
        closePopupForWindow(ev.source);
        return;
      }
      if(data && data.type === 'yomi-add'){
        openAddModal(String(data.q || ''));
        return;
      }
      if(data && data.type === 'yomi-lookup' && data.q){
        var sourceBox = popupForWindow(ev.source);
        if (SUBLOOKUP_MODE === 'nested' && sourceBox) {
          try {
            var pt = nestedPopupPoint(sourceBox, data.anchor);
            showIframe(
              String(data.q),
              pt.x,
              pt.y,
              /*noPush=*/true,
              /*absXY=*/true,
              /*keepExisting=*/true
            );
          } catch (_) {
            var nx = (window.__lastMouseX || 60), ny = (window.__lastMouseY || 60);
            showIframe(String(data.q), nx, ny, /*noPush=*/true, /*absXY=*/false, /*keepExisting=*/true);
          }
          return;
        }
        // Reuse current popup position: keep left/top unchanged
        var have = sourceBox || document.getElementById('hanzi-mini-iframe');
        if (have){
          try{
            var rect = have.getBoundingClientRect();
            var left = Math.round(rect.left);
            var top  = Math.round(rect.top);
            showIframe(String(data.q), left, top, /*noPush=*/false, /*absXY=*/true);
          }catch(_){
            // fallback to last mouse position
            var mx = (window.__lastMouseX || 60), my = (window.__lastMouseY || 60);
            showIframe(String(data.q), mx, my);
          }
        } else {
          // if no popup yet, open near last mouse
          var mx = (window.__lastMouseX || 60), my = (window.__lastMouseY || 60);
          showIframe(String(data.q), mx, my);
        }
      }
    }catch(e){}
  }, false);

  // Track last mouse position for better placement
  window.addEventListener('mousemove', function(e){
    window.__lastMouseX = e.clientX; window.__lastMouseY = e.clientY;
  }, {passive:true});


  // ==== Language-aware character filter ====
  const MODES = Array.isArray(window.__hanziLangs) && window.__hanziLangs.length
    ? window.__hanziLangs
    : [window.__hanziLang || 'zh'];
  const POPUP_MOD = ['none', 'alt', 'ctrl', 'shift', 'meta', 'hover_shift'].includes(window.__yomiPopupModifier)
    ? window.__yomiPopupModifier
    : 'none';
  const SUBLOOKUP_MODE = window.__yomiSublookupMode === 'nested' ? 'nested' : 'reuse';
  const CHAR_RE_LIST = MODES.map(function(mode){
    if (mode === 'ja') return /[\u3040-\u30ff\u4e00-\u9fffー]/;
    if (mode === 'ko') return /[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]/;
    if (mode === 'en') return /[A-Za-z]/;
    if (['fr','de','es','sq','pt','it','id','vi','la','pl','sh','eo','eu','ga','sga','tl'].includes(mode)) return /[A-Za-z\u00c0-\u024f]/;
    if (mode === 'ru') return /[\u0400-\u04ff]/;
    if (mode === 'el' || mode === 'grc') return /[\u0370-\u03ff\u1f00-\u1fff]/;
    if (mode === 'ar') return /[\u0600-\u06ff\ufb50-\ufdff\ufe70-\ufeff]/;
    if (mode === 'th') return /[\u0e00-\u0e7f]/;
    if (mode === 'ka') return /[\u10a0-\u10ff\u1c90-\u1cbf]/;
    if (mode === 'aii') return /[\u0700-\u074f]/;
    if (mode === 'yi') return /[\u0590-\u05ff]/;
    return /[\u3400-\u9fff\u{20000}-\u{2A6DF}]/u;
  });
  function hasLangChar(s){ return !!(s && CHAR_RE_LIST.some(function(re){ return re.test(s); })); }
  function isLookupChar(ch){
    return !!(ch && CHAR_RE_LIST.some(function(re){ return re.test(ch); }));
  }
  function caretRangeAtPoint(x, y){
    try{
      if (document.caretRangeFromPoint) {
        return document.caretRangeFromPoint(x, y);
      }
      if (document.caretPositionFromPoint) {
        const pos = document.caretPositionFromPoint(x, y);
        if (!pos) return null;
        const r = document.createRange();
        r.setStart(pos.offsetNode, pos.offset);
        r.collapse(true);
        return r;
      }
    }catch(_){}
    return null;
  }
  function textNodeFromRange(r){
    if (!r) return null;
    let node = r.startContainer;
    if (!node) return null;
    if (node.nodeType === Node.TEXT_NODE) return node;
    if (node.childNodes && node.childNodes.length) {
      const i = Math.max(0, Math.min(r.startOffset || 0, node.childNodes.length - 1));
      node = node.childNodes[i];
      if (node && node.nodeType === Node.TEXT_NODE) return node;
    }
    return null;
  }
  function lookupTextAtPoint(x, y){
    const r = caretRangeAtPoint(x, y);
    const node = textNodeFromRange(r);
    if (!node || !root.contains(node)) return null;
    const value = node.nodeValue || '';
    if (!value) return null;
    let pos = Math.max(0, Math.min(r.startOffset || 0, value.length));
    if (!isLookupChar(value.charAt(pos)) && pos > 0 && isLookupChar(value.charAt(pos - 1))) {
      pos -= 1;
    }
    if (!isLookupChar(value.charAt(pos))) return null;
    let start = pos;
    let end = pos + 1;
    while (start > 0 && isLookupChar(value.charAt(start - 1))) start -= 1;
    while (end < value.length && isLookupChar(value.charAt(end))) end += 1;
    const text = value.slice(start, end).trim();
    if (!text || text.length > 80 || !hasLangChar(text)) return null;
    const rr = document.createRange();
    rr.setStart(node, start);
    rr.setEnd(node, end);
    let rect = null;
    try { rect = rr.getBoundingClientRect(); } catch(_){}
    return {text, rect};
  }

  // ----- selection helpers -----
  function getSel() {
    const sel = window.getSelection && window.getSelection();
    if (!sel || !sel.rangeCount) return { text:'', rect:null };
    const rng = sel.getRangeAt(0);
    const node = rng.commonAncestorContainer;
    if (!root.contains(node)) return { text:'', rect:null };
    let rect=null; try{ const r=rng.getBoundingClientRect(); if(r) rect=r; }catch(e){}
    return { text:(sel.toString()||'').trim(), rect };
  }

  // ====== POPUP: Lookup iframe ======
  let outsideHandler = null;

  function allPopupBoxes(){
    return Array.from(document.querySelectorAll('.hanzi-mini-popup, #hanzi-mini-iframe'));
  }

  function popupForWindow(win){
    if (!win) return null;
    const boxes = allPopupBoxes();
    for (const box of boxes) {
      const ifr = box && box.querySelector && box.querySelector('iframe');
      if (ifr && ifr.contentWindow === win) return box;
    }
    return null;
  }

  function closePopupBox(box){
    if (!box) return false;
    box.remove();
    return true;
  }

  function closePopupForWindow(win){
    return closePopupBox(popupForWindow(win));
  }

  function popupSize(){
    return {
      w: 380,
      h: Math.min(Math.max(320, Math.round(window.innerHeight * 0.45)), 720)
    };
  }

  function clampPopupPoint(x, y, w, h){
    const pad = 12;
    const maxX = Math.max(pad, window.innerWidth - w - pad);
    const maxY = Math.max(pad, window.innerHeight - h - pad);
    return {
      x: Math.max(pad, Math.min(Math.round(x), maxX)),
      y: Math.max(pad, Math.min(Math.round(y), maxY))
    };
  }

  function nestedPopupPoint(sourceBox, anchor){
    const size = popupSize();
    let ax = 42, ay = 34, aw = 1, ah = 1;
    if (anchor && Number.isFinite(Number(anchor.x)) && Number.isFinite(Number(anchor.y))) {
      ax = Number(anchor.x) || 0;
      ay = Number(anchor.y) || 0;
      aw = Math.max(1, Number(anchor.w) || 1);
      ah = Math.max(1, Number(anchor.h) || 1);
    }
    const sr = sourceBox.getBoundingClientRect();
    const left = sr.left + ax;
    const top = sr.top + ay;
    const right = left + aw;
    const bottom = top + ah;
    const gap = 10;

    let x = right + gap;
    if (x + size.w > window.innerWidth - 12) {
      x = left - size.w - gap;
    }
    if (x < 12) {
      x = left + gap;
    }

    let y = top;
    if (y + size.h > window.innerHeight - 12) {
      y = bottom - size.h;
    }
    return clampPopupPoint(x, y, size.w, size.h);
  }

  function closeBox() {
    allPopupBoxes().forEach(function(b){ if (b) b.remove(); });
    if (outsideHandler) {
      root.removeEventListener('mousedown', outsideHandler, true);
      outsideHandler = null;
    }
  }

  function enableOutsideClose() {
    if (outsideHandler) {
      root.removeEventListener('mousedown', outsideHandler, true);
      outsideHandler = null;
    }
    // chỉ nghe trong #qa để không ảnh hưởng Deck
    outsideHandler = function(ev) {
      const boxes = allPopupBoxes();
      if (!boxes.length) return;
      const addPanel = document.getElementById('yomi-add-modal');
      if (addPanel && addPanel.contains(ev.target)) return; // đừng đóng khi click vào panel Add
      if (!boxes.some(function(box){ return box.contains(ev.target); })) {
        closeBox();
      }
    };
    root.addEventListener('mousedown', outsideHandler, true);
  }

  // ====== History Back/Forward ======
  const __hist = []; // mỗi item: { q, x, y }
  let __idx = -1;

  function __pushHist(q, x, y){
    if(!q) return;
    if(__idx < __hist.length - 1){
      __hist.splice(__idx + 1);
    }
    if(__idx >= 0){
      const cur = __hist[__idx];
      if(cur && cur.q === q && cur.x === x && cur.y === y) return;
    }
    __hist.push({ q: String(q), x: Math.round(x||60), y: Math.round(y||60) });
    __idx = __hist.length - 1;
    __updateNavButtons();
  }

  function __canBack(){ return __idx > 0; }
  function __canFwd(){ return __idx < __hist.length - 1; }

  function __goBack(){
    if(!__canBack()) return;
    __idx -= 1;
    const it = __hist[__idx];
    let x = (it && Number.isFinite(it.x)) ? it.x : (window.__lastMouseX||60);
    let y = (it && Number.isFinite(it.y)) ? it.y : (window.__lastMouseY||60);
    const box = document.getElementById('hanzi-mini-iframe');
    if (box) { try { const r = box.getBoundingClientRect(); x = Math.round(r.left); y = Math.round(r.top); } catch(_){} }
    showIframe(it.q, x, y, true, /*absXY=*/true);
__updateNavButtons();
  }

  function __goFwd(){
    if(!__canFwd()) return;
    __idx += 1;
    const it = __hist[__idx];
    let x = (it && Number.isFinite(it.x)) ? it.x : (window.__lastMouseX||60);
    let y = (it && Number.isFinite(it.y)) ? it.y : (window.__lastMouseY||60);
    const box = document.getElementById('hanzi-mini-iframe');
    if (box) { try { const r = box.getBoundingClientRect(); x = Math.round(r.left); y = Math.round(r.top); } catch(_){} }
    showIframe(it.q, x, y, true, /*absXY=*/true);
__updateNavButtons();
  }

  // giữ tham chiếu nút back/fwd mới tạo để enable/disable
  let __btnBack = null, __btnFwd = null;
  function __updateNavButtons(){
    if(__btnBack) __btnBack.disabled = !__canBack();
    if(__btnFwd)  __btnFwd.disabled  = !__canFwd();
    try{
      const ifr = document.querySelector('#hanzi-mini-iframe iframe');
      if(ifr && ifr.contentWindow){
        ifr.contentWindow.postMessage({
          type:'yomi-navstate',
          canBack:__canBack(),
          canFwd:__canFwd()
        }, '*');
      }
    }catch(_){}
  }


// Helper: unified hover + disabled styles for nav-like buttons
function __styleNavBtn(btn){
  if(!btn) return;
  // base look
  btn.style.border = 'none';
  btn.style.background = 'transparent';
  btn.style.cursor = btn.disabled ? 'default' : 'pointer';
  btn.style.transition = 'background .12s ease, box-shadow .12s ease, opacity .12s ease';
  btn.style.borderRadius = '5px';   // bo góc cho hover nhỏ gọn hơn
  btn.style.padding = '0';          // tránh phình to

  // bỏ focus khi click chuột (nhưng vẫn giữ cho Tab bằng bàn phím)
  btn.addEventListener('mousedown', function(e){ e.preventDefault(); }, {passive:false});
  btn.addEventListener('mouseup', function(){ try{ btn.blur(); }catch(_){} });
  // hover
  btn.addEventListener('mouseenter', function(){
    if(!btn.disabled){
      // thay background = box-shadow để trông nhỏ gọn hơn
      btn.style.boxShadow = 'inset 0 0 0 12px #f1e8d8'; // vòng tròn 12px
    }
  });
  btn.addEventListener('mouseleave', function(){
    btn.style.boxShadow = 'none';
  });
}


  let __popupSeq = 0;
  function showIframe(text, x, y, noPush /*NEW*/, absXY /*NEW*/, keepExisting /*NEW*/ ) {
    // dọn popup/listener cũ nếu có
    if (!keepExisting) closeBox();

    const url = 'http://127.0.0.1:8777/lookup?q=' + encodeURIComponent(text);

    // Kích thước: ngang cố định, cao theo viewport
    const size = popupSize();
    const W = size.w;
    const H = size.h;

    // ⬇️ Nếu absXY=true: (x,y) là left/top tuyệt đối; nếu không, lệch +10 cho đẹp
    const rawX = Math.round(x || 40), rawY = Math.round(y || 40);
    const point = clampPopupPoint(absXY ? rawX : rawX + 10, absXY ? rawY : rawY + 10, W, H);
    const left = point.x;
    const top  = point.y;

    const box = document.createElement('div');
    __popupSeq += 1;
    box.id = keepExisting ? ('hanzi-mini-iframe-' + __popupSeq) : 'hanzi-mini-iframe';
    box.className = 'hanzi-mini-popup';
    box.style.position = 'fixed';
    box.style.left = left + 'px';
    box.style.top  = top  + 'px';
    box.style.zIndex = '99999';
    box.style.background = '#fff8ee';
    box.style.border = '1px solid #e0c8a7';
    box.style.borderRadius = '18px';
    box.style.boxShadow = '0 8px 24px rgba(0,0,0,.18)';
    box.style.overflow = 'hidden';
    box.style.pointerEvents = 'auto';

    __btnBack = null;
    __btnFwd = null;

    const ifr = document.createElement('iframe');
    ifr.src = url;
    ifr.width = String(W);
    ifr.height = String(H);
    ifr.setAttribute('frameborder', '0');
    ifr.style.display = 'block';
    ifr.style.background = 'transparent';
    ifr.style.borderRadius = '18px';
    ifr.style.overflow = 'hidden';
    box.appendChild(ifr);

    document.body.appendChild(box);
    enableOutsideClose();

    // cho add modal reload lại iframe sau khi thêm
    if (!keepExisting) {
      window.__yomiReloadLookup = () => { try { ifr.src = new URL(ifr.src).toString(); } catch(_){} };
    }

    // cập nhật history (NEW) — lưu luôn tọa độ mở lần này
    if (!keepExisting && !noPush) { __pushHist(String(text || ''), left, top); }
    if (!keepExisting) __updateNavButtons();
  }

  // ====== MODAL: Add-to-DB (center, big, overlay) ======
  let modalBackdrop = null;

  // cache danh sách sources theo phiên
  if (!window.__yomiSrcCache) window.__yomiSrcCache = null;

  function openAddModal(initialWord) {
    closeAddModal(); // reset

    // backdrop
    modalBackdrop = document.createElement('div');
    modalBackdrop.id = 'yomi-modal-backdrop';
    modalBackdrop.style.position = 'fixed';
    modalBackdrop.style.left = '0';
    modalBackdrop.style.top = '0';
    modalBackdrop.style.width = '100vw';
    modalBackdrop.style.height = '100vh';
    modalBackdrop.style.background = 'rgba(0,0,0,.22)';
    modalBackdrop.style.zIndex = '100000';
    modalBackdrop.style.backdropFilter = 'blur(0.5px)';
    modalBackdrop.addEventListener('mousedown', (e)=>{ if (e.target === modalBackdrop) closeAddModal(); });
    document.body.appendChild(modalBackdrop);

    // modal
    const panel = document.createElement('div');
    panel.id = 'yomi-add-modal';
    panel.style.position = 'fixed';
    panel.style.left = '50%';
    panel.style.top  = '50%';
    panel.style.transform = 'translate(-50%, -50%)';
    panel.style.width = '520px';
    panel.style.maxWidth = '92vw';
    panel.style.maxHeight = '82vh';
    panel.style.overflow = 'auto';
    panel.style.background = '#ffffff';
    panel.style.border = '1px solid #e0c8a7';
    panel.style.borderRadius = '8px';
    panel.style.boxShadow = '0 16px 36px rgba(0,0,0,.28)';
    panel.style.padding = '12px';
    panel.style.zIndex = '100001';
    panel.style.pointerEvents = 'auto';

    panel.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
        <div style="font:600 14px system-ui;color:#674d2a">Add to DB</div>
        <button id="yomi-add-close" title="Close" style="border:none;background:transparent;font:18px/20px system-ui;cursor:pointer">×</button>
      </div>

      <label style="display:block;font:12px system-ui;color:#6b5a42">Word</label>
      <input id="yomi-term" type="text" style="width:100%;margin:2px 0 8px;padding:8px 10px;border:1px solid #e0c8a7;border-radius:10px;font:13px system-ui" />

      <label style="display:block;font:12px system-ui;color:#6b5a42">Reading</label>
      <input id="yomi-reading" type="text" style="width:100%;margin:2px 0 8px;padding:8px 10px;border:1px solid #e0c8a7;border-radius:10px;font:13px system-ui" />

      <label style="display:block;font:12px system-ui;color:#6b5a42">Gloss rows (one entry per line)</label>
      <div id="yomi-rows"></div>
      <div style="display:flex;justify-content:flex-end;margin:6px 0 10px">
        <button id="yomi-addrow" type="button"
          style="padding:6px 10px;border:1px solid #c79f73;border-radius:9px;background:#f6e7d2;cursor:pointer">＋ Add row</button>
      </div>

      <div class="row-flex">
        <div class="grow">
          <label style="display:block;font:12px system-ui;color:#6b5a42">Dictionary</label>
          <select id="yomi-src"
            style="width:100%;margin:2px 0 6px;padding:8px 10px;border:1px solid #e0c8a7;border-radius:10px;font:13px system-ui"></select>
        </div>
        <button id="yomi-src-refresh" class="shrink" title="Reload list"
          style="height:34px;margin-top:18px;padding:0 10px;border:1px solid #c79f73;border-radius:9px;background:#fff;cursor:pointer">
          ↻
        </button>
      </div>

      <input id="yomi-newtitle" type="text" placeholder="New dictionary title..."
        style="display:none;width:100%;margin:2px 0 8px;padding:8px 10px;border:1px solid #e0c8a7;border-radius:10px;font:13px system-ui" />

      <div id="yomi-msg" style="font:12px system-ui;color:#a24;padding:2px 0 6px;display:none;"></div>

      <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:6px">
        <button id="yomi-cancel" style="padding:8px 12px;border:1px solid #dcc3a5;border-radius:10px;background:#fff;cursor:pointer">Cancel</button>
        <button id="yomi-save"   style="padding:8px 14px;border:1px solid #c79f73;border-radius:10px;background:#f6e7d2;cursor:pointer">Save</button>
      </div>
    `;
    const styleFix = document.createElement('style');
    styleFix.textContent = `
      #yomi-add-modal, #yomi-add-modal * { box-sizing: border-box; }
      #yomi-add-modal .row-flex { display: flex; align-items: center; gap: 8px; }
      #yomi-add-modal .grow { flex: 1 1 auto; min-width: 0; }
      #yomi-add-modal .shrink { flex: 0 0 auto; }
      #yomi-add-modal .yomi-row { display:flex; align-items:center; gap:6px; }
      #yomi-add-modal .yomi-row input { flex:1 1 auto; min-width:0; }
    `;
    panel.prepend(styleFix);

    modalBackdrop.appendChild(panel);

    // fields
    const termEl = panel.querySelector('#yomi-term');
    const readEl = panel.querySelector('#yomi-reading');
    const srcEl  = panel.querySelector('#yomi-src');
    const newEl  = panel.querySelector('#yomi-newtitle');
    const closeEl= panel.querySelector('#yomi-add-close');
    const msgEl  = panel.querySelector('#yomi-msg');
    const btnRef = panel.querySelector('#yomi-src-refresh');

    termEl.value = (initialWord || '').trim();
    termEl.focus(); termEl.select();

    // rows
    const rowsEl = panel.querySelector('#yomi-rows');
    const addRowBtn = panel.querySelector('#yomi-addrow');

    function addGlossRow(val = '') {
      const row = document.createElement('div');
      row.className = 'yomi-row';
      row.style.display = 'flex';
      row.style.gap = '6px';
      row.style.margin = '4px 0';

      const inp = document.createElement('textarea');
      inp.type = 'text';
      inp.className = 'yomi-row-input';
      inp.value = val;
      inp.placeholder = 'One definition per line...';
      inp.style.flex = '1';
      inp.style.padding = '8px 10px';
      inp.style.border = '1px solid #e0c8a7';
      inp.style.borderRadius = '10px';
      inp.style.font = '13px system-ui';
	  inp.style.height = '100px';   // chỉnh cao hơn tuỳ ý
      inp.style.resize = 'vertical'; // cho resize bằng chuột nếu muốn
      inp.style.minWidth = '0';
	  
      inp.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey) {
          e.preventDefault();
          addGlossRow('');
        }
      });

      const del = document.createElement('button');
      del.textContent = '×';
      del.title = 'Remove row';
      del.style.width = '32px';
      del.style.height = '32px';
      del.style.border = '1px solid #e0c8a7';
      del.style.borderRadius = '10px';
      del.style.background = '#fff';
      del.style.cursor = 'pointer';
      del.onclick = () => row.remove();

      row.appendChild(inp);
      row.appendChild(del);
      rowsEl.appendChild(row);
      inp.focus();
    }
    addRowBtn.onclick = () => addGlossRow('');
    addGlossRow('');

    // sources helpers
    function fillSources(j) {
      srcEl.innerHTML = '';
      let hadAny = false;
      if (j && j.ok && Array.isArray(j.sources) && j.sources.length) {
        j.sources.forEach(s => {
          const opt = document.createElement('option');
          opt.value = String(s.id);
          opt.textContent = s.title + (s.enabled ? '' : ' (disabled)');
          srcEl.appendChild(opt);
        });
        hadAny = true;
      }
      const optNew = document.createElement('option');
      optNew.value = 'NEW';
      optNew.textContent = '＋ Create new dictionary…';
      srcEl.appendChild(optNew);
      srcEl.value = hadAny ? srcEl.options[0].value : 'NEW';
      newEl.style.display = (srcEl.value === 'NEW') ? 'block' : 'none';
    }
    async function loadSources(forceReload=false) {
      msgEl.style.display = 'none';
      if (!window.__yomiSrcCache || forceReload) {
        try {
          const j = await fetch('http://127.0.0.1:8777/api/sources').then(r => r.json());
          window.__yomiSrcCache = j;
        } catch (e) {
          window.__yomiSrcCache = {ok:false, sources:[]};
          msgEl.textContent = 'Could not load dictionary list. You can create a new one.';
          msgEl.style.display = 'block';
        }
      }
      fillSources(window.__yomiSrcCache || {ok:false, sources:[]});
    }
    btnRef.onclick = () => loadSources(true);
    loadSources(false);

    srcEl.addEventListener('change', () => {
      newEl.style.display = (srcEl.value === 'NEW') ? 'block' : 'none';
      if (srcEl.value === 'NEW') { newEl.focus(); }
    });

    // actions
    panel.querySelector('#yomi-cancel').onclick = () => closeAddModal();
    closeEl.onclick = () => closeAddModal();

    panel.querySelector('#yomi-save').onclick = async () => {
      const term = termEl.value.trim();
      if (!term) { termEl.focus(); return; }
      const reading = readEl.value.trim();

      const lines = Array.from(panel.querySelectorAll('.yomi-row-input'))
        .map(e => e.value.trim())
        .filter(Boolean);
      const gloss = lines.join('\n');

      const choice = srcEl.value;
      const payload = {
        term, reading, gloss,
        source_id: (choice && choice !== 'NEW') ? Number(choice) : null,
        new_source_title: (choice === 'NEW') ? (newEl.value.trim()) : ''
      };
      try {
        const res = await fetch('http://127.0.0.1:8777/api/add', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify(payload)
        }).then(r => r.json());
        if (res && res.ok) {
          closeAddModal();
          if (typeof window.__yomiReloadLookup === 'function') {
            window.__yomiReloadLookup();
          }
        } else {
          alert('Add failed: ' + (res && res.error ? res.error : 'unknown'));
        }
      } catch (e) {
        alert('Add failed: ' + e);
      }
    };
  }

  function closeAddModal() {
    if (modalBackdrop) {
      modalBackdrop.remove();
      modalBackdrop = null;
    }
  }

  // ----- hotkeys & mouse (chỉ gắn trên #qa) -----
  let lastText='', lastRect=null, lastMouse={x:40,y:40};
  function cacheSel() { const s=getSel(); lastText=s.text; lastRect=s.rect; }
  function onMouseMove(e){ lastMouse = {x:e.clientX||40, y:e.clientY||40}; }
  function popupModifierHeld(e){
    if (POPUP_MOD === 'none') return true;
    if (POPUP_MOD === 'alt') return !!(e && e.altKey);
    if (POPUP_MOD === 'ctrl') return !!(e && e.ctrlKey);
    if (POPUP_MOD === 'shift') return !!(e && e.shiftKey);
    if (POPUP_MOD === 'meta') return !!(e && e.metaKey);
    if (POPUP_MOD === 'hover_shift') return false;
    return true;
  }
  function popupModifierKeyPressed(e){
    if (!e) return false;
    if (POPUP_MOD === 'alt') return e.key === 'Alt';
    if (POPUP_MOD === 'ctrl') return e.key === 'Control';
    if (POPUP_MOD === 'shift') return e.key === 'Shift';
    if (POPUP_MOD === 'meta') return e.key === 'Meta';
    if (POPUP_MOD === 'hover_shift') return e.key === 'Shift';
    return false;
  }
  function showSelectionAt(x, y, retry){
    const s = getSel();
    const text = s.text || lastText;
    if (!text && retry !== false) {
      setTimeout(function(){ showSelectionAt(x, y, false); }, 35);
      return false;
    }
    if (!hasLangChar(text)) return false;
    const rect = s.rect || lastRect;
    if (rect && (!x || !y)) {
      x = Math.round(rect.left + rect.width / 2);
      y = Math.round(rect.top + Math.min(rect.height, 24));
    }
    showIframe(text, x || lastMouse.x || 40, y || lastMouse.y || 40);
    return true;
  }
  function showHoverText(){
    const s = getSel();
    if (hasLangChar(s.text)) {
      let x = lastMouse.x || window.__lastMouseX || 40;
      let y = lastMouse.y || window.__lastMouseY || 40;
      if (s.rect) {
        x = Math.round(s.rect.left + s.rect.width / 2);
        y = Math.round(s.rect.top + Math.min(s.rect.height, 24));
      }
      showIframe(s.text, x, y);
      return true;
    }
    const hit = lookupTextAtPoint(lastMouse.x || window.__lastMouseX || 40, lastMouse.y || window.__lastMouseY || 40);
    if (!hit) return false;
    let x = lastMouse.x || window.__lastMouseX || 40;
    let y = lastMouse.y || window.__lastMouseY || 40;
    if (hit.rect) {
      x = Math.round(hit.rect.left + hit.rect.width / 2);
      y = Math.round(hit.rect.top + Math.min(hit.rect.height, 24));
    }
    showIframe(hit.text, x, y);
    return true;
  }

  // Mở khi tô đen + thả chuột. Nếu có modifier thì chỉ mở khi giữ đúng phím.
  function onMouseUp(e){
    if (!root.contains(e.target)) return;
    if (!popupModifierHeld(e)) return;
    setTimeout(function(){ showSelectionAt(e.clientX || 40, e.clientY || 40); }, 0);
  }
  // Double-click cũng mở, theo cùng trigger.
  function onDblClick(e){
    if (!root.contains(e.target)) return;
    if (!popupModifierHeld(e)) return;
    setTimeout(function(){ showSelectionAt(e.clientX || 40, e.clientY || 40); }, 0);
  }

  function onKeyDown(e){
    if (e.__yomiPopupKeyHandled) return;
    e.__yomiPopupKeyHandled = true;
    // Đóng nhanh
    if (e.key === 'Escape') { closeAddModal(); closeBox(); return; }

    // Modifier trigger: chọn text trước rồi bấm Opt/Ctrl/Shift/Cmd để mở.
    if (POPUP_MOD !== 'none' && popupModifierKeyPressed(e)) {
      if (POPUP_MOD === 'hover_shift') showHoverText();
      else showSelectionAt();
      return;
    }

    // Ctrl+Shift+D: bật góc cố định
    if (e.ctrlKey && e.shiftKey && (e.key==='D' || e.key==='d')) {
      const s=getSel(); if (hasLangChar(s.text)) showIframe(s.text, 40, 40); return;
    }

    // Ctrl+Shift=A: mở modal Add từ selection (kể cả chưa mở popup tra)
    if (e.ctrlKey && e.shiftKey && (e.key==='A' || e.key==='a')) {
      const s = getSel();
      const text = s.text || lastText;
      if (!text) return;
      openAddModal(text);
      return;
    }
  }

  // gắn listener
  root.addEventListener('keyup',   cacheSel,   {passive:true});
  root.addEventListener('mouseup', cacheSel,   {passive:true});
  root.addEventListener('mousemove', onMouseMove, {passive:true});
  root.addEventListener('mouseup',   onMouseUp,   {passive:true});
  root.addEventListener('dblclick',  onDblClick,  {passive:true});
  root.addEventListener('keydown',   onKeyDown,   {passive:true});
  document.addEventListener('keydown', onKeyDown, true);
  document.addEventListener('selectionchange', cacheSel, true);

  // cleanup
  window.__hanziMiniCleanup = function(){
    root.removeEventListener('keyup',    cacheSel,   {passive:true});
    root.removeEventListener('mouseup',  cacheSel,   {passive:true});
    root.removeEventListener('mousemove', onMouseMove, {passive:true});
    root.removeEventListener('mouseup',  onMouseUp,   {passive:true});
    root.removeEventListener('dblclick', onDblClick,  {passive:true});
    root.removeEventListener('keydown',  onKeyDown,   {passive:true});
    document.removeEventListener('keydown', onKeyDown, true);
    document.removeEventListener('selectionchange', cacheSel, true);
    closeAddModal();
    const b=document.getElementById('hanzi-mini-iframe'); if (b) b.remove();
    root.__hanziMiniInjected = false;
    delete window.__yomiReloadLookup;
  };
})();
