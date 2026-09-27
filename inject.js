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

const __resizeCSS = document.createElement('style');
__resizeCSS.textContent = `
  .hanzi-mini-popup .yomilens-resize-handle { position:absolute; z-index:2; touch-action:none; user-select:none; }
  .hanzi-mini-popup .yomilens-resize-top,
  .hanzi-mini-popup .yomilens-resize-bottom { left:14px; right:14px; height:8px; cursor:ns-resize; }
  .hanzi-mini-popup .yomilens-resize-top { top:0; }
  .hanzi-mini-popup .yomilens-resize-bottom { bottom:0; }
  .hanzi-mini-popup .yomilens-resize-left,
  .hanzi-mini-popup .yomilens-resize-right { top:14px; bottom:14px; width:8px; cursor:ew-resize; }
  .hanzi-mini-popup .yomilens-resize-left { left:0; }
  .hanzi-mini-popup .yomilens-resize-right { right:0; }
  .hanzi-mini-popup .yomilens-resize-top-left,
  .hanzi-mini-popup .yomilens-resize-top-right,
  .hanzi-mini-popup .yomilens-resize-bottom-left,
  .hanzi-mini-popup .yomilens-resize-bottom-right { width:14px; height:14px; }
  .hanzi-mini-popup .yomilens-resize-top-left { top:0; left:0; cursor:nwse-resize; }
  .hanzi-mini-popup .yomilens-resize-top-right { top:0; right:0; cursor:nesw-resize; }
  .hanzi-mini-popup .yomilens-resize-bottom-left { bottom:0; left:0; cursor:nesw-resize; }
  .hanzi-mini-popup .yomilens-resize-bottom-right { bottom:0; right:0; cursor:nwse-resize; }
`;
document.head.appendChild(__resizeCSS);


  // Listen for requests from iframe to lookup a sub-component
  function onWindowMessage(ev){
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
        var curHist = (__idx >= 0 && __hist[__idx]) ? __hist[__idx] : null;
        var returnQ = (data.termChar && curHist && curHist.q && curHist.q !== String(data.q))
          ? String(curHist.q)
          : "";
        if (SUBLOOKUP_MODE === 'disabled' && sourceBox && !data.termChar) return;
        if (data.termChar && sourceBox) {
          reusePopup(sourceBox, String(data.q), returnQ, !!PREFER_KANJI_CLICK);
          return;
        }
        if (SUBLOOKUP_MODE === 'nested' && sourceBox) {
          try {
            var pt = nestedPopupPoint(sourceBox, data.anchor);
            showIframe(
              String(data.q),
              pt.x,
              pt.y,
              /*noPush=*/true,
              /*absXY=*/true,
              /*keepExisting=*/true,
              /*returnQ=*/returnQ,
              /*anchorRect=*/null,
              /*preserveHookMark=*/false,
              /*openKanjiTab=*/!!(data.termChar && PREFER_KANJI_CLICK)
            );
          } catch (_) {
            var nx = (window.__lastMouseX || 60), ny = (window.__lastMouseY || 60);
            showIframe(
              String(data.q), nx, ny,
              /*noPush=*/true, /*absXY=*/false, /*keepExisting=*/true,
              /*returnQ=*/returnQ, /*anchorRect=*/null,
              /*preserveHookMark=*/false,
              /*openKanjiTab=*/!!(data.termChar && PREFER_KANJI_CLICK)
            );
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
            if(data.termChar && PREFER_KANJI_CLICK) showIframe(String(data.q), left, top, false, true, false, returnQ, null, false, true);
            else showIframe(String(data.q), left, top, /*noPush=*/false, /*absXY=*/true, /*keepExisting=*/false, returnQ);
          }catch(_){
            // fallback to last mouse position
            var mx = (window.__lastMouseX || 60), my = (window.__lastMouseY || 60);
            if(data.termChar && PREFER_KANJI_CLICK) showIframe(String(data.q), mx, my, false, false, false, returnQ, null, false, true);
            else showIframe(String(data.q), mx, my, /*noPush=*/false, /*absXY=*/false, /*keepExisting=*/false, returnQ);
          }
        } else {
          // if no popup yet, open near last mouse
          var mx = (window.__lastMouseX || 60), my = (window.__lastMouseY || 60);
          if(data.termChar && PREFER_KANJI_CLICK) showIframe(String(data.q), mx, my, false, false, false, returnQ, null, false, true);
          else showIframe(String(data.q), mx, my, /*noPush=*/false, /*absXY=*/false, /*keepExisting=*/false, returnQ);
        }
      }
    }catch(e){}
  }
  window.addEventListener('message', onWindowMessage, false);

  // Track last mouse position for better placement
  function onWindowMouseMove(e){
    window.__lastMouseX = e.clientX; window.__lastMouseY = e.clientY;
  }
  window.addEventListener('mousemove', onWindowMouseMove, {passive:true});


  // ==== Language-aware character filter ====
  const MODES = Array.isArray(window.__hanziLangs) && window.__hanziLangs.length
    ? window.__hanziLangs
    : [window.__hanziLang || 'zh'];
  const POPUP_MOD = ['none', 'alt', 'ctrl', 'shift', 'meta'].includes(window.__yomiPopupModifier)
    ? window.__yomiPopupModifier
    : 'none';
  const SUBLOOKUP_MODE = window.__yomiSublookupMode === 'nested' ? 'nested' : (window.__yomiSublookupMode === 'disabled' ? 'disabled' : 'reuse');
  const HOVER_SHIFT = !!window.__yomiHoverShiftMode;
  const PREFER_KANJI_CLICK = !!window.__yomiPreferKanjiOnClick;
  const POPUP_THEME = String(window.__yomiPopupTheme || 'default');
  const POPUP_SHELL = ({
    default: {bg:'#fff8ee', border:'#e0c8a7'},
    aux_bluets: {bg:'#fbf7ed', border:'#ded2bd'},
    emerald_spring: {bg:'#f2f6ed', border:'#d3dbcd'},
    showa_matcha: {bg:'#f6f0dc', border:'#d7cfae'},
    sakura_city_pop: {bg:'#fff3f5', border:'#efd2dc'},
    sakura_night: {
      bg:'#252633', border:'#41424f',
      shadow:'0 14px 34px rgba(0,0,0,.48), 0 0 20px rgba(192,86,64,.08)'
    },
    lotus_noir: {
      bg:'#061b29', border:'#244656',
      shadow:'0 14px 34px rgba(0,0,0,.5), 0 0 20px rgba(76,201,240,.07)'
    },
    violet_circuit: {
      bg:'#2e3440', border:'#4c566a',
      shadow:'0 14px 34px rgba(0,0,0,.46), 0 0 20px rgba(136,192,208,.06)'
    }
  })[POPUP_THEME] || {bg:'#fff8ee', border:'#e0c8a7'};
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
    if (!allPopupBoxes().length) clearHookMark();
    return true;
  }

  function closePopupForWindow(win){
    return closePopupBox(popupForWindow(win));
  }

  function popupSize(){
    const customW = Number(window.__yomiPopupWidth);
    const customH = Number(window.__yomiPopupHeight);
    return {
      w: (customW && customW >= 200 && customW <= 1200) ? customW : 380,
      h: (customH && customH >= 200 && customH <= 1200) ? customH : 350
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

  function popupPointFromAnchor(rect, w, h){
    if (!rect) return null;
    const pad = 12;
    const gap = 12;
    const left = Number(rect.left || 0);
    const right = Number.isFinite(Number(rect.right)) ? Number(rect.right) : left + Number(rect.width || 0);
    const top = Number(rect.top || 0);
    const bottom = Number.isFinite(Number(rect.bottom)) ? Number(rect.bottom) : top + Number(rect.height || 0);
    let x = ((left + right) / 2) - (w / 2);
    let y = top - h - gap;
    if (y < pad) y = bottom + gap;
    return clampPopupPoint(x, y, w, h);
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

  function closeBox(preserveHookMark) {
    allPopupBoxes().forEach(function(b){ if (b) b.remove(); });
    if (outsideHandler) {
      document.removeEventListener('mousedown', outsideHandler, true);
      outsideHandler = null;
    }
    if (!preserveHookMark) clearHookMark();
  }

  function enableOutsideClose() {
    if (outsideHandler) {
      document.removeEventListener('mousedown', outsideHandler, true);
      outsideHandler = null;
    }
    outsideHandler = function(ev) {
      const boxes = allPopupBoxes();
      if (!boxes.length) return;
      const addPanel = document.getElementById('yomi-add-modal');
      if (addPanel && addPanel.contains(ev.target)) return; // đừng đóng khi click vào panel Add
      if (!boxes.some(function(box){ return box.contains(ev.target); })) {
        closeBox();
      }
    };
    document.addEventListener('mousedown', outsideHandler, true);
  }

  function addResizeHandles(box, ifr) {
    const directions = ['top', 'right', 'bottom', 'left', 'top-left', 'top-right', 'bottom-left', 'bottom-right'];
    directions.forEach(function(direction) {
      const handle = document.createElement('div');
      handle.className = 'yomilens-resize-handle yomilens-resize-' + direction;
      handle.setAttribute('aria-label', 'Resize popup ' + direction);
      handle.addEventListener('pointerdown', function(start) {
        if (start.button !== 0) return;
        start.preventDefault();
        start.stopPropagation();
        const rect = box.getBoundingClientRect();
        const previousSelect = document.body.style.userSelect;
        const previousCursor = document.body.style.cursor;
        document.body.style.userSelect = 'none';
        document.body.style.cursor = window.getComputedStyle(handle).cursor;
        handle.setPointerCapture(start.pointerId);

        function move(ev) {
          if (ev.pointerId !== start.pointerId || !box.isConnected) return;
          ev.preventDefault();
          const dx = ev.clientX - start.clientX;
          const dy = ev.clientY - start.clientY;
          const minW = Math.min(320, window.innerWidth - 24);
          const minH = Math.min(240, window.innerHeight - 24);
          const right = rect.right, bottom = rect.bottom;
          const left = direction.includes('left') ? Math.max(12, Math.min(right - minW, rect.left + dx)) : rect.left;
          const top = direction.includes('top') ? Math.max(12, Math.min(bottom - minH, rect.top + dy)) : rect.top;
          const width = direction.includes('left') ? right - left
            : direction.includes('right') ? Math.max(minW, Math.min(window.innerWidth - rect.left - 12, rect.width + dx)) : rect.width;
          const height = direction.includes('top') ? bottom - top
            : direction.includes('bottom') ? Math.max(minH, Math.min(window.innerHeight - rect.top - 12, rect.height + dy)) : rect.height;
          box.style.left = Math.round(left) + 'px';
          box.style.top = Math.round(top) + 'px';
          box.style.width = Math.round(width) + 'px';
          box.style.height = Math.round(height) + 'px';
          ifr.width = String(Math.round(width));
          ifr.height = String(Math.round(height));
        }

        function stop(ev) {
          if (ev.pointerId !== start.pointerId) return;
          handle.removeEventListener('pointermove', move);
          handle.removeEventListener('pointerup', stop);
          handle.removeEventListener('pointercancel', stop);
          if (handle.hasPointerCapture(start.pointerId)) handle.releasePointerCapture(start.pointerId);
          document.body.style.userSelect = previousSelect;
          document.body.style.cursor = previousCursor;

          const resized = box.getBoundingClientRect();
          const width = Math.max(200, Math.min(1200, Math.round(resized.width)));
          const height = Math.max(200, Math.min(1200, Math.round(resized.height)));
          window.__yomiPopupWidth = width;
          window.__yomiPopupHeight = height;
          if (typeof window.pycmd === 'function') {
            window.pycmd('yomilens:set-popup-size:' + width + ':' + height);
          }
        }
        handle.addEventListener('pointermove', move);
        handle.addEventListener('pointerup', stop);
        handle.addEventListener('pointercancel', stop);
      });
      box.appendChild(handle);
    });
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
  function popupLookupUrl(text, returnQ, openKanjiTab) {
    let url = 'http://127.0.0.1:8777/lookup?q=' + encodeURIComponent(text) + '&mode=' + encodeURIComponent(SUBLOOKUP_MODE);
    if (returnQ) url += '&return_q=' + encodeURIComponent(returnQ);
    if (openKanjiTab) url += '&tab=kanji';
    return url;
  }

  function reusePopup(box, text, returnQ, openKanjiTab) {
    if (!box || !box.isConnected) return false;
    const ifr = box.querySelector('iframe');
    if (!ifr) return false;
    const rect = box.getBoundingClientRect();
    ifr.src = popupLookupUrl(text, returnQ, openKanjiTab);
    window.__yomiReloadLookup = () => {
      try { ifr.src = new URL(ifr.src).toString(); } catch (_) {}
    };
    __pushHist(String(text || ''), Math.round(rect.left), Math.round(rect.top));
    __updateNavButtons();
    return true;
  }

  function showIframe(text, x, y, noPush /*NEW*/, absXY /*NEW*/, keepExisting /*NEW*/, returnQ /*NEW*/, anchorRect /*NEW*/, preserveHookMark /*NEW*/, openKanjiTab /*NEW*/ ) {
    // dọn popup/listener cũ nếu có
    if (!keepExisting) closeBox(!!preserveHookMark);

    const url = popupLookupUrl(text, returnQ, openKanjiTab);

    // Kích thước: ngang cố định, cao theo viewport
    const size = popupSize();
    const W = size.w;
    const H = size.h;

    // ⬇️ Nếu absXY=true: (x,y) là left/top tuyệt đối; nếu không, lệch +10 cho đẹp
    const rawX = Math.round(x || 40), rawY = Math.round(y || 40);
    const point = popupPointFromAnchor(anchorRect, W, H)
      || clampPopupPoint(absXY ? rawX : rawX + 10, absXY ? rawY : rawY + 10, W, H);
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
    box.style.background = POPUP_SHELL.bg;
    box.style.border = '1px solid ' + POPUP_SHELL.border;
    box.style.borderRadius = '18px';
    box.style.boxShadow = POPUP_SHELL.shadow || '0 8px 24px rgba(0,0,0,.18)';
    box.style.overflow = 'hidden';
    box.style.pointerEvents = 'auto';
    box.style.width = W + 'px';
    box.style.height = H + 'px';

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
    addResizeHandles(box, ifr);

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
    const modalDark =
      document.documentElement.classList.contains('nightMode') ||
      document.body.classList.contains('nightMode') ||
      window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (modalDark) panel.classList.add('yomi-modal-dark');

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
      #yomi-add-modal.yomi-modal-dark {
        color:#f4f2f6 !important;
        background:#272733 !important;
        border-color:#5f5d70 !important;
      }
      #yomi-add-modal.yomi-modal-dark label,
      #yomi-add-modal.yomi-modal-dark > div:first-of-type > div {
        color:#f4f2f6 !important;
      }
      #yomi-add-modal.yomi-modal-dark input,
      #yomi-add-modal.yomi-modal-dark textarea,
      #yomi-add-modal.yomi-modal-dark select {
        color:#f8f7fa !important;
        background:#383744 !important;
        border-color:#777487 !important;
        color-scheme:dark;
      }
      #yomi-add-modal.yomi-modal-dark input::placeholder,
      #yomi-add-modal.yomi-modal-dark textarea::placeholder { color:#aaa7b5 !important; }
      #yomi-add-modal.yomi-modal-dark button {
        color:#f4f2f6 !important;
        background:#383744 !important;
        border-color:#777487 !important;
      }
      #yomi-add-modal.yomi-modal-dark #yomi-addrow,
      #yomi-add-modal.yomi-modal-dark #yomi-save {
        color:#fff !important;
        background:#c05640 !important;
        border-color:#df806d !important;
      }
      #yomi-add-modal.yomi-modal-dark button:disabled { color:#8f8c99 !important; opacity:.65; }
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
      // Loading the source list is asynchronous. Preserve an in-progress
      // "Create new dictionary" choice and its draft title when it finishes.
      const previousSource = srcEl.value;
      const draftTitle = newEl.value;
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
      const previousStillExists = Array.from(srcEl.options).some(
        opt => opt.value === previousSource
      );
      srcEl.value = previousStillExists
        ? previousSource
        : (hadAny ? srcEl.options[0].value : 'NEW');
      newEl.value = draftTitle;
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

  // ==== Hook + Shift: hover over text while holding Shift ====
  let __hoverTimer = null;
  let __hoverLastKey = '';
  let __hoverSeq = 0;
  let __hoverAbort = null;
  let __hookOverlays = [];
  const __hookNodeIds = new WeakMap();
  const __hookScanCache = new Map();
  let __hookNodeSeq = 0;
  const HOVER_DEBOUNCE_MS = 65;
  const HOOK_CJK_MAX_LEN = 16;
  const HOOK_WORD_MAX_LEN = 64;
  const HOOK_EXCLUDED = '.hanzi-mini-popup,#hanzi-mini-iframe,#yomi-add-modal,input,textarea,select,button,script,style,noscript,rt,rp';
  const HOOK_CJK_RE = /[\u3040-\u30ff\u3400-\u9fff\u{20000}-\u{2A6DF}\uac00-\ud7a3ー]/u;
  const HOOK_WORD_RE = /[A-Za-z\u00c0-\u024f\u0370-\u04ff\u0590-\u074f\u0e00-\u0e7f\u10a0-\u10ff\u1c90-\u1cbf'’-]/u;

  const __hookCSS = document.createElement('style');
  __hookCSS.textContent = `
    ::highlight(yomi-hook) {
      background: rgba(255, 200, 80, 0.48);
      color: inherit;
      text-decoration: none;
    }
    .yomi-hook-overlay {
      position: fixed;
      z-index: 99998;
      pointer-events: none;
      background: rgba(255, 200, 80, 0.42);
      border: 1px solid rgba(210, 160, 60, 0.72);
      border-radius: 3px;
    }
  `;
  document.head.appendChild(__hookCSS);

  function clearHookMark() {
    try { if (window.CSS && CSS.highlights) CSS.highlights.delete('yomi-hook'); } catch (_) {}
    __hookOverlays.forEach(function(el){ try { el.remove(); } catch (_) {} });
    __hookOverlays = [];
  }

  function cancelHoverWork(resetKey) {
    if (__hoverTimer) { clearTimeout(__hoverTimer); __hoverTimer = null; }
    if (__hoverAbort) { try { __hoverAbort.abort(); } catch (_) {} }
    __hoverAbort = null;
    __hoverSeq += 1;
    if (resetKey) __hoverLastKey = '';
  }

  function isExcludedHookNode(node) {
    const parent = node && node.nodeType === 3 ? node.parentElement : node;
    return !parent || !root.contains(parent) || !!(parent.closest && parent.closest(HOOK_EXCLUDED));
  }

  function nextHookTextNode(node) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function(candidate){
        return isExcludedHookNode(candidate) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
      }
    });
    walker.currentNode = node;
    return walker.nextNode();
  }

  function pushHookUnit(units, node, start, end, char) {
    units.push({node:node, start:start, end:end, char:char});
  }

  function hookCharRect(node, index) {
    const text = node && node.textContent ? node.textContent : '';
    if (!node || index < 0 || index >= text.length) return null;
    try {
      const range = document.createRange();
      range.setStart(node, index);
      range.setEnd(node, index + 1);
      const rects = Array.from(range.getClientRects()).filter(function(rect){
        return rect && rect.width > 0 && rect.height > 0;
      });
      if (!rects.length) return null;
      return rects[0];
    } catch (_) { return null; }
  }

  function hookRectDistance(rect, x, y) {
    const dx = x < rect.left ? rect.left - x : (x > rect.right ? x - rect.right : 0);
    const dy = y < rect.top ? rect.top - y : (y > rect.bottom ? y - rect.bottom : 0);
    const centerDx = x - (rect.left + rect.right) / 2;
    const centerDy = y - (rect.top + rect.bottom) / 2;
    return {edge:dx * dx + dy * dy, center:centerDx * centerDx + centerDy * centerDy};
  }

  function hookOffsetAtPoint(node, caretOffset, x, y) {
    const text = node && node.textContent ? node.textContent : '';
    if (!text.length) return 0;
    const candidates = [];
    [caretOffset - 1, caretOffset, caretOffset + 1].forEach(function(index){
      if (index < 0 || index >= text.length || candidates.some(function(item){ return item.index === index; })) return;
      const rect = hookCharRect(node, index);
      if (!rect) return;
      const distance = hookRectDistance(rect, x, y);
      candidates.push({index:index, edge:distance.edge, center:distance.center});
    });
    if (!candidates.length) return Math.min(Math.max(0, caretOffset), text.length - 1);
    candidates.sort(function(a, b){ return a.edge - b.edge || a.center - b.center; });
    return candidates[0].index;
  }

  function caretAtPoint(x, y) {
    if (document.caretPositionFromPoint) {
      const pos = document.caretPositionFromPoint(x, y);
      if (pos && pos.offsetNode && pos.offsetNode.nodeType === 3) {
        return {node:pos.offsetNode, offset:hookOffsetAtPoint(pos.offsetNode, pos.offset, x, y)};
      }
    }
    if (document.caretRangeFromPoint) {
      const range = document.caretRangeFromPoint(x, y);
      if (range && range.startContainer && range.startContainer.nodeType === 3) {
        return {node:range.startContainer, offset:hookOffsetAtPoint(range.startContainer, range.startOffset, x, y)};
      }
    }
    return null;
  }

  function getRawTextUnderCursor(x, y) {
    const caret = caretAtPoint(x, y);
    if (!caret || isExcludedHookNode(caret.node)) return null;
    let node = caret.node;
    let text = node.textContent || '';
    let offset = Math.min(Math.max(0, caret.offset), Math.max(0, text.length - 1));
    if (!text[offset] && offset > 0) offset -= 1;
    if (!text[offset] || !hasLangChar(text[offset])) return null;
    const cjkMode = HOOK_CJK_RE.test(text[offset]);
    const maxLen = cjkMode ? HOOK_CJK_MAX_LEN : HOOK_WORD_MAX_LEN;
    if (!cjkMode) {
      while (offset > 0 && HOOK_WORD_RE.test(text[offset - 1])) offset -= 1;
    }
    const units = [];
    let output = '';
    let firstNode = true;
    while (node && output.length < maxLen) {
      if (isExcludedHookNode(node)) break;
      text = node.textContent || '';
      let i = firstNode ? offset : 0;
      firstNode = false;
      for (; i < text.length && output.length < maxLen; i += 1) {
        const ch = text[i];
        if (/\s/u.test(ch)) {
          // A Latin lookup is word-scoped: never let a phrase entry swallow
          // neighbouring words (for example "bring it back" when hovering
          // "bring"). CJK keeps its cross-node/BR behaviour intentionally.
          if (!cjkMode) return output ? {text:output, units:units} : null;
          continue;
        }
        const accepted = cjkMode ? HOOK_CJK_RE.test(ch) : HOOK_WORD_RE.test(ch);
        // Preserve word-internal hyphens and apostrophes for Latin-script
        // dictionary queries. CJK keeps skipping punctuation between glyphs.
        if (!accepted && cjkMode && /\p{P}/u.test(ch)) continue;
        if (!accepted) return output ? {text:output.replace(/\s+$/u, ''), units:units.slice(0, output.replace(/\s+$/u, '').length)} : null;
        output += ch;
        pushHookUnit(units, node, i, i + 1, ch);
      }
      node = nextHookTextNode(node);
    }
    const clean = output.replace(/\s+$/u, '');
    return clean ? {text:clean, units:units.slice(0, clean.length)} : null;
  }

  function hookRange(info, matchLen) {
    const units = info && Array.isArray(info.units) ? info.units : [];
    const count = Math.max(1, Math.min(units.length, Number(matchLen || units.length)));
    if (!units.length || !count) return null;
    try {
      const range = document.createRange();
      range.setStart(units[0].node, units[0].start);
      range.setEnd(units[count - 1].node, units[count - 1].end);
      return range;
    } catch (_) { return null; }
  }

  function applyHookMark(info, matchLen) {
    clearHookMark();
    const range = hookRange(info, matchLen);
    if (!range) return null;
    try {
      if (window.CSS && CSS.highlights && window.Highlight) {
        CSS.highlights.set('yomi-hook', new Highlight(range));
      } else {
        Array.from(range.getClientRects()).forEach(function(rect){
          if (!rect.width || !rect.height) return;
          const overlay = document.createElement('div');
          overlay.className = 'yomi-hook-overlay';
          overlay.style.left = (rect.left - 1) + 'px';
          overlay.style.top = (rect.top - 1) + 'px';
          overlay.style.width = (rect.width + 2) + 'px';
          overlay.style.height = (rect.height + 2) + 'px';
          document.body.appendChild(overlay);
          __hookOverlays.push(overlay);
        });
      }
      return range.getBoundingClientRect();
    } catch (_) { return null; }
  }

  function hookNodeKey(info) {
    const unit = info && info.units && info.units[0];
    if (!unit || !unit.node) return info ? info.text : '';
    if (!__hookNodeIds.has(unit.node)) __hookNodeIds.set(unit.node, ++__hookNodeSeq);
    return __hookNodeIds.get(unit.node) + ':' + unit.start + ':' + info.text;
  }

  function hookCacheGet(key) {
    if (!__hookScanCache.has(key)) return null;
    const value = __hookScanCache.get(key);
    __hookScanCache.delete(key);
    __hookScanCache.set(key, value);
    return value;
  }

  function hookCacheSet(key, value) {
    __hookScanCache.delete(key);
    __hookScanCache.set(key, value);
    if (__hookScanCache.size > 500) __hookScanCache.delete(__hookScanCache.keys().next().value);
  }

  function onHoverShiftMove(e) {
    if (!HOVER_SHIFT || !e.shiftKey || !root.contains(e.target) || (e.target.closest && e.target.closest(HOOK_EXCLUDED))) {
      cancelHoverWork(true);
      if (!allPopupBoxes().length) clearHookMark();
      return;
    }
    const selection = window.getSelection && window.getSelection();
    if (selection && !selection.isCollapsed && String(selection.toString() || '').trim()) {
      cancelHoverWork(true);
      clearHookMark();
      return;
    }
    const boxes = allPopupBoxes();
    if (boxes.some(function(b){ return b && b.contains(e.target); })) return;

    if (__hoverTimer) { clearTimeout(__hoverTimer); __hoverTimer = null; }
    __hoverTimer = setTimeout(function() {
      __hoverTimer = null;
      const activeSelection = window.getSelection && window.getSelection();
      if (activeSelection && !activeSelection.isCollapsed && String(activeSelection.toString() || '').trim()) return;
      const info = getRawTextUnderCursor(e.clientX, e.clientY);
      if (!info || !info.text || !hasLangChar(info.text)) {
        __hoverLastKey = '';
        clearHookMark();
        return;
      }
      const key = hookNodeKey(info);
      if (key === __hoverLastKey) return;
      __hoverLastKey = key;
      const seq = ++__hoverSeq;
      const cached = hookCacheGet(info.text);
      if (cached) {
        const cachedLen = Number(cached.matchLen || 0);
        const cachedText = cachedLen > 0 ? info.text.slice(0, cachedLen) : info.text;
        const cachedRect = applyHookMark(info, cachedLen || info.units.length);
        showIframe(cachedText, e.clientX || 40, e.clientY || 40, false, false, false, null, cachedRect, true);
        return;
      }
      if (__hoverAbort) { try { __hoverAbort.abort(); } catch (_) {} }
      __hoverAbort = new AbortController();
      const signal = __hoverAbort.signal;
      fetch('http://127.0.0.1:8777/api/scan?q=' + encodeURIComponent(info.text), {signal:signal})
        .then(function(r){ return r.json(); })
        .then(function(data){
          if (seq !== __hoverSeq || signal.aborted) return;
          const matchLen = (data && data.matchLen) || 0;
          hookCacheSet(info.text, {matchLen:matchLen});
          const matchedText = matchLen > 0 ? info.text.slice(0, matchLen) : info.text;
          const rect = applyHookMark(info, matchLen || info.units.length);
          showIframe(matchedText, e.clientX || 40, e.clientY || 40, false, false, false, null, rect, true);
        })
        .catch(function(err){
          if (seq !== __hoverSeq || signal.aborted || (err && err.name === 'AbortError')) return;
          const rect = applyHookMark(info, info.units.length);
          showIframe(info.text, e.clientX || 40, e.clientY || 40, false, false, false, null, rect, true);
        });
    }, HOVER_DEBOUNCE_MS);
  }

  function onHoverKeyUp(e) {
    if (!HOVER_SHIFT) return;
    if (e.key === 'Shift') {
      cancelHoverWork(true);
    }
  }

  function onHookViewportChange(){
    if (!allPopupBoxes().length) clearHookMark();
  }
  function popupModifierHeld(e){
    if (POPUP_MOD === 'none') return true;
    if (POPUP_MOD === 'alt') return !!(e && e.altKey);
    if (POPUP_MOD === 'ctrl') return !!(e && e.ctrlKey);
    if (POPUP_MOD === 'shift') return !!(e && e.shiftKey);
    if (POPUP_MOD === 'meta') return !!(e && e.metaKey);
    return true;
  }
  function popupModifierKeyPressed(e){
    if (!e) return false;
    if (POPUP_MOD === 'alt') return e.key === 'Alt';
    if (POPUP_MOD === 'ctrl') return e.key === 'Control';
    if (POPUP_MOD === 'shift') return e.key === 'Shift';
    if (POPUP_MOD === 'meta') return e.key === 'Meta';
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
    const addModal = document.getElementById('yomi-add-modal');
    if (addModal && e.target && addModal.contains(e.target)) {
      // Typing a source title may use Shift/Ctrl/Opt/Cmd. These keystrokes
      // belong to the form and must never trigger a lookup behind the modal.
      if (e.key === 'Escape') closeAddModal();
      return;
    }
    // Đóng nhanh
    if (e.key === 'Escape') { closeAddModal(); closeBox(); return; }

    // Modifier trigger: chọn text trước rồi bấm Opt/Ctrl/Shift/Cmd để mở.
    if (POPUP_MOD !== 'none' && popupModifierKeyPressed(e)) {
      showSelectionAt();
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
  root.addEventListener('mousemove', onHoverShiftMove, {passive:true});
  document.addEventListener('keyup', onHoverKeyUp, true);
  document.addEventListener('keydown', onKeyDown, true);
  document.addEventListener('selectionchange', cacheSel, true);
  document.addEventListener('scroll', onHookViewportChange, true);
  window.addEventListener('resize', onHookViewportChange, {passive:true});

  // cleanup
  window.__hanziMiniCleanup = function(){
    closeBox();
    window.removeEventListener('message', onWindowMessage, false);
    window.removeEventListener('mousemove', onWindowMouseMove, {passive:true});
    root.removeEventListener('keyup',    cacheSel,   {passive:true});
    root.removeEventListener('mouseup',  cacheSel,   {passive:true});
    root.removeEventListener('mousemove', onMouseMove, {passive:true});
    root.removeEventListener('mouseup',  onMouseUp,   {passive:true});
    root.removeEventListener('dblclick', onDblClick,  {passive:true});
    root.removeEventListener('keydown',  onKeyDown,   {passive:true});
    root.removeEventListener('mousemove', onHoverShiftMove, {passive:true});
    document.removeEventListener('keyup', onHoverKeyUp, true);
    document.removeEventListener('keydown', onKeyDown, true);
    document.removeEventListener('selectionchange', cacheSel, true);
    document.removeEventListener('scroll', onHookViewportChange, true);
    window.removeEventListener('resize', onHookViewportChange, {passive:true});
    cancelHoverWork(true);
    clearHookMark();
    closeAddModal();
    __focusCSS.remove();
    __resizeCSS.remove();
    root.__hanziMiniInjected = false;
    delete window.__yomiReloadLookup;
  };
})();
