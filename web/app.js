/* 天诺影像 · 商场店销售看板 */
(function () {
  'use strict';

  // 静态托管模式（GitHub Pages 等）：数据直接嵌在页面里，没有后台服务。
  // 由 zb_static.py 生成时注入 window.__DATA__ / window.__PRODUCTS__。
  var STATIC = window.__STATIC__ ? (window.__DATA__ || null) : null;
  var STATIC_PRODUCTS = window.__STATIC__ ? (window.__PRODUCTS__ || null) : null;

  var state = {
    scope: '商场店',
    preset: '今年',
    start: '',
    end: '',
    custom: false,
    data: null,
    colorOf: {},
    q: '',
    filterStore: '',
    filterPerson: '',
    // 产品视图
    view: 'sales',
    pdata: null,
    pq: '',
    pfilterCat: '',
    pfilterStore: '',
    anchor: ''
  };

  // 门店三色：墨黑 / 徕卡红 / 石板灰 —— 和「去年同期」的空心柱明确区分开
  var PALETTE = ['#14161A', '#E20613', '#7B8794', '#B4BAC3', '#5A6068', '#C9CED5', '#2B2F36', '#9AA1AA'];

  function catColor(name) {
    var map = {
      '相机': '#14161A', '镜头': '#5A5A5A', '配件': '#8C929B', '投影电视': '#E20613',
      '望远镜': '#C4C4C4', '周边': '#B0B0B0', '服务': '#D8D8D8', '其他数码': '#7A0810', '其他': '#E8E8E8'
    };
    return map[name] || '#8C929B';
  }
  var SERIES_COLOR = ['#14161A', '#E20613', '#5A5A5A', '#8C929B', '#B0B0B0', '#C4C4C4', '#D8D8D8', '#2B2B2B', '#7A0810', '#E8E8E8'];

  // 按人拆解时的配色：7 个人要能一眼分开，所以用了多色相。
  // 刻意避开绿色 —— 这个看板里绿色代表「上涨」，当分类色会误导。
  var PERSON_COLOR = [
    '#14161A',  // 墨黑
    '#E20613',  // 徕卡红
    '#2B6CB0',  // 钢蓝
    '#C77700',  // 琥珀
    '#6B4E9E',  // 紫
    '#5A6672',  // 石板灰
    '#A3AAB4',  // 浅灰
    '#8C4A2F',  // 赭石
    '#0F6E8C',  // 青
    '#B07AA1'   // 藕荷
  ];

  function personColor(index) {
    return PERSON_COLOR[index % PERSON_COLOR.length];
  }

  var $ = function (id) { return document.getElementById(id); };

  /* ==================== 产品分类视图 ==================== */
  function loadProducts(opts) {
    opts = opts || {};
    if (state.pdata) { renderProducts(); return; }
    if (STATIC) {                    // 静态页：用嵌好的数据
      if (STATIC_PRODUCTS) {
        state.pdata = STATIC_PRODUCTS;
        renderProducts();
      } else {
        showError('这个静态页里没有产品分类数据。');
      }
      return;
    }
    loading(true, '正在读取产品明细…');
    showError('');
    fetch('/api/products' + queryString())
      .then(function (r) {
        return r.json().then(function (j) {
          if (!r.ok || j.error) throw new Error(j.error || ('HTTP ' + r.status));
          return j;
        });
      })
      .then(function (j) {
        state.pdata = j;
        renderProducts();
        loading(false);
      })
      .catch(function (e) {
        loading(false);
        showError('产品数据加载失败：' + e.message);
        toast('产品数据加载失败', true);
      });
  }

  function queryString() {
    var p = '范围=' + encodeURIComponent(state.scope);
    if (state.start || state.end) {
      p += '&start=' + encodeURIComponent(state.start) + '&end=' + encodeURIComponent(state.end);
    } else {
      p += '&时间=' + encodeURIComponent(state.preset);
    }
    return '?' + p;
  }

  function renderProducts() {
    var d = state.pdata;
    if (!d) return;
    renderPKpis();
    renderCatList();
    renderCamSeries();
    renderModelTable();
    renderStoreCamTable();
    renderPDetail();
  }

  function renderPKpis() {
    var d = state.pdata;
    var cams = d['相机系列'] || [];
    var camAmt = cams.reduce(function (a, x) { return a + x['金额']; }, 0);
    var camQty = cams.reduce(function (a, x) { return a + x['数量']; }, 0);
    var total = d['总计'];
    var cond = d['相机新旧'] || [];
    var used = cond.filter(function (x) { return x['名称'] === '二手'; })[0];
    var usedShare = used ? used['占比'] : 0;

    var items = [
      { lbl: '相机销售额', val: moneyShort(camAmt), unit: '元', sub: '精确 ' + money(camAmt) + ' 元' },
      { lbl: '相机台数', val: int(camQty), unit: '台', sub: '占总业绩 ' + pct(total && total['金额'] ? camAmt / total['金额'] : 0) },
      { lbl: '二手相机占比', val: pct(usedShare), unit: '', sub: '二手 ' + int(used ? used['数量'] : 0) + ' 台 · 全新 ' + int(camQty - (used ? used['数量'] : 0)) + ' 台' },
      { lbl: '产品行 / 合同', val: int(total['产品行']), unit: '行', sub: '涉及 ' + int(total['合同数']) + ' 份合同' }
    ];
    $('pkpis').innerHTML = items.map(function (it) {
      return '<div class="kpi"><div class="lbl">' + it.lbl + '</div>' +
        '<div class="val">' + it.val + (it.unit ? '<span class="unit">' + it.unit + '</span>' : '') + '</div>' +
        '<div class="sub">' + it.sub + '</div></div>';
    }).join('');
  }

  function barList(rows, colorOf, nameHead) {
    var total = rows.reduce(function (a, x) { return a + x['金额']; }, 0) || 1;
    return '<table><thead><tr><th>' + nameHead + '</th><th class="num">数量</th>' +
      '<th class="num">金额</th><th style="width:130px">占比</th><th class="num">占比</th>' +
      '<th class="num">涉及合同</th></tr></thead><tbody>' +
      rows.map(function (r) {
        // colorOf 可能是对象（按名字查）也可能是函数（按名字算）
        var col = '#8C929B';
        if (typeof colorOf === 'function') col = colorOf(r['名称']) || '#8C929B';
        else if (colorOf) col = colorOf[r['名称']] || '#8C929B';
        return '<tr>' +
          '<td><span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:' + col + ';margin-right:7px"></span>' + esc(r['名称']) + '</td>' +
          '<td class="num">' + int(r['数量']) + '</td>' +
          '<td class="num"><b>' + money(r['金额']) + '</b></td>' +
          '<td><div class="bar"><i style="width:' + (r['金额'] / total * 100).toFixed(1) + '%;background:' + col + '"></i></div></td>' +
          '<td class="num">' + pct(r['占比']) + '</td>' +
          '<td class="num" style="color:var(--muted)">' + int(r['合同数']) + '</td>' +
        '</tr>';
      }).join('') + '</tbody></table>';
  }

  function renderCatList() {
    var d = state.pdata;
    $('catHint').textContent = '合计 ' + money(d['总计']['金额']) + ' 元';
    $('catList').innerHTML = barList(d['按品类'] || [], catColor, '品类');
  }

  function renderCamSeries() {
    var d = state.pdata;
    var rows = d['相机系列'] || [];
    var total = rows.reduce(function (a, x) { return a + x['金额']; }, 0) || 1;
    $('camSeries').innerHTML = rows.map(function (r, i) {
      var col = SERIES_COLOR[i % SERIES_COLOR.length];
      return '<div class="store">' +
        '<div class="store-head">' +
          donut(r['金额'] / total, col) +
          '<div style="flex:1;min-width:0">' +
            '<div><span class="store-name">' + esc(r['名称']) + '</span></div>' +
            '<div class="store-nums">' +
              '<div class="store-num"><div class="n">' + int(r['数量']) + '</div><div class="t">台</div></div>' +
              '<div class="store-num"><div class="n">' + moneyShort(r['金额']) + '</div><div class="t">销售额（元）</div></div>' +
              '<div class="store-num"><div class="n">' + pct(r['占比']) + '</div><div class="t">占相机</div></div>' +
            '</div>' +
          '</div>' +
        '</div></div>';
    }).join('') || '<div class="empty">没有相机数据</div>';
  }

  function renderModelTable() {
    var d = state.pdata;
    var rows = d['相机型号'] || [];
    var total = rows.reduce(function (a, x) { return a + x['金额']; }, 0) || 1;
    $('modelHint').textContent = rows.length + ' 个型号 · 相机合计 ' + money(total) + ' 元';
    $('modelTable').innerHTML =
      '<thead><tr><th class="mid">排名</th><th>型号</th><th class="num">台数</th>' +
      '<th class="num">销售额</th><th style="width:150px">占比</th><th class="num">占比</th>' +
      '<th class="num">平均单价</th><th class="num">涉及合同</th></tr></thead><tbody>' +
      (rows.length ? rows.map(function (r, i) {
        return '<tr>' +
          '<td class="mid"><span class="rank r' + (i + 1) + '">' + (i + 1) + '</span></td>' +
          '<td><b>' + esc(r['名称']) + '</b></td>' +
          '<td class="num">' + int(r['数量']) + '</td>' +
          '<td class="num"><b>' + money(r['金额']) + '</b></td>' +
          '<td><div class="bar"><i style="width:' + (r['金额'] / total * 100).toFixed(1) + '%"></i></div></td>' +
          '<td class="num">' + pct(r['占比']) + '</td>' +
          '<td class="num">' + money(r['数量'] ? r['金额'] / r['数量'] : 0) + '</td>' +
          '<td class="num" style="color:var(--muted)">' + int(r['合同数']) + '</td>' +
        '</tr>';
      }).join('') : '<tr><td colspan="8" class="empty">没有数据</td></tr>') + '</tbody>';
  }

  function renderStoreCamTable() {
    var d = state.pdata;
    var stores = (d['按门店'] || []).map(function (x) { return x['名称']; });
    var detail = d['明细'] || [];
    var rows = stores.map(function (st) {
      var items = detail.filter(function (x) { return x['门店'] === st; });
      var cams = items.filter(function (x) { return x['品类'] === '相机'; });
      var amt = items.reduce(function (a, x) { return a + x['金额']; }, 0);
      var camAmt = cams.reduce(function (a, x) { return a + x['金额']; }, 0);
      var byModel = {};
      cams.forEach(function (x) { byModel[x['型号']] = (byModel[x['型号']] || 0) + x['数量']; });
      var top = Object.keys(byModel).sort(function (a, b) { return byModel[b] - byModel[a]; }).slice(0, 4);
      return { store: st, amt: amt, camAmt: camAmt, qty: cams.length,
               share: amt ? camAmt / amt : 0,
               top: top.map(function (m) { return m + '(' + int(byModel[m]) + ')'; }).join('、') };
    }).sort(function (a, b) { return b.camAmt - a.camAmt; });

    $('storeCamTable').innerHTML =
      '<thead><tr><th>门店</th><th class="num">总业绩</th><th class="num">相机金额</th>' +
      '<th class="num">相机台数</th><th style="width:120px">相机占比</th><th class="num">占比</th>' +
      '<th>热销型号</th></tr></thead><tbody>' +
      rows.map(function (r) {
        return '<tr>' +
          '<td><a class="person-link" data-pstore="' + esc(r.store) + '">' + esc(r.store) + '</a></td>' +
          '<td class="num">' + money(r.amt) + '</td>' +
          '<td class="num"><b>' + money(r.camAmt) + '</b></td>' +
          '<td class="num">' + int(r.qty) + '</td>' +
          '<td><div class="bar"><i style="width:' + (r.share * 100).toFixed(1) + '%"></i></div></td>' +
          '<td class="num">' + pct(r.share) + '</td>' +
          '<td style="color:var(--muted)">' + esc(r.top) + '</td>' +
        '</tr>';
      }).join('') + '</tbody>';
  }

  function renderPDetail() {
    var d = state.pdata;
    var cats = (d['按品类'] || []).map(function (x) { return x['名称']; });
    var stores = (d['按门店'] || []).map(function (x) { return x['名称']; });
    var selC = $('pfilterCat'), selS = $('pfilterStore');
    if (selC.options.length !== cats.length + 1) {
      selC.innerHTML = '<option value="">全部品类</option>' + cats.map(function (c) {
        return '<option value="' + esc(c) + '">' + esc(c) + '</option>'; }).join('');
    }
    if (selS.options.length !== stores.length + 1) {
      selS.innerHTML = '<option value="">全部门店</option>' + stores.map(function (c) {
        return '<option value="' + esc(c) + '">' + esc(c) + '</option>'; }).join('');
    }
    selC.value = state.pfilterCat;
    selS.value = state.pfilterStore;

    var q = state.pq.trim().toLowerCase();
    var rows = (d['明细'] || []).filter(function (r) {
      if (state.pfilterCat && r['品类'] !== state.pfilterCat) return false;
      if (state.pfilterStore && r['门店'] !== state.pfilterStore) return false;
      if (!q) return true;
      return (r['产品名'] + ' ' + r['型号'] + ' ' + r['销售员'] + ' ' + r['门店'] + ' ' + r['htid'])
        .toLowerCase().indexOf(q) >= 0;
    });
    rows.sort(function (a, b) { return (b['日期'] || '').localeCompare(a['日期'] || ''); });

    var CAP = 400;
    $('pdetailCount').textContent = '共 ' + int(rows.length) + ' 行' +
      (rows.length > CAP ? '（只显示最近 ' + CAP + ' 行）' : '');

    $('pdetailTable').innerHTML =
      '<thead><tr><th class="mid">日期</th><th>门店</th><th>销售员</th><th>品类</th><th>系列</th>' +
      '<th>型号</th><th>新旧</th><th class="num">数量</th><th class="num">金额</th>' +
      '<th>产品全名</th></tr></thead><tbody>' +
      (rows.length ? rows.slice(0, CAP).map(function (r) {
        var col = catColor(r['品类']) || '#8C929B';
        return '<tr>' +
          '<td class="mid">' + esc(r['日期'] || '—') + '</td>' +
          '<td>' + esc(r['门店']) + '</td>' +
          '<td>' + esc(r['销售员']) + '</td>' +
          '<td><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:' + col + ';margin-right:5px"></span>' + esc(r['品类']) + '</td>' +
          '<td style="color:var(--muted)">' + esc(r['系列'] || '—') + '</td>' +
          '<td><b>' + esc(r['型号']) + '</b></td>' +
          '<td>' + (r['新旧'] === '二手' ? '<span style="color:#c0392b">二手</span>' : esc(r['新旧'])) + '</td>' +
          '<td class="num">' + int(r['数量']) + '</td>' +
          '<td class="num">' + money(r['金额']) + '</td>' +
          '<td style="color:var(--muted)">' + esc(r['产品名']) + '</td>' +
        '</tr>';
      }).join('') : '<tr><td colspan="10" class="empty">没有匹配的产品</td></tr>') + '</tbody>';
  }

  function switchView(view) {
    state.view = view;
    $('viewSales').classList.toggle('hidden', view !== 'sales');
    $('viewProducts').classList.toggle('hidden', view !== 'product');
    [].forEach.call($('viewChips').children, function (c) {
      c.classList.toggle('active', c.dataset.view === view);
    });
    if (view === 'product') loadProducts();
  }

  /* ---------------- URL 状态（可收藏 / 可分享） ---------------- */
  function readHash() {
    var h = (location.hash || '').replace(/^#/, '');
    if (!h) return;
    // 纯锚点（没有 =）是页面内定位，不是视图状态，单独存起来
    if (h.indexOf('=') < 0) { state.anchor = h; return; }
    var p = new URLSearchParams(h);
    if (p.get('scope')) state.scope = p.get('scope');
    if (p.get('start') || p.get('end')) {
      state.start = p.get('start') || '';
      state.end = p.get('end') || '';
      state.custom = true;
    } else if (p.get('preset')) {
      state.preset = p.get('preset');
    }
    if (p.get('q')) { state.q = p.get('q'); }
    if (p.get('store')) { state.filterStore = p.get('store'); }
    if (p.get('view')) { state.view = p.get('view'); }
  }

  function writeHash() {
    // 本地和线上保持一致：都记筛选状态。
    // （线上只有预生成的「本月」一份数据，所以这里主要记 q / store / view，
    //   切换区间在线上仍然点不动 —— 那是数据只有一份的限制，不是这个的问题。）
    var p = new URLSearchParams();
    p.set('scope', state.scope);
    if (state.start || state.end) {
      if (state.start) p.set('start', state.start);
      if (state.end) p.set('end', state.end);
    } else {
      p.set('preset', state.preset);
    }
    if (state.q) p.set('q', state.q);
    if (state.filterStore) p.set('store', state.filterStore);
    if (state.view && state.view !== 'sales') p.set('view', state.view);
    try { history.replaceState(null, '', '#' + p.toString()); } catch (e) { /* file:// 下忽略 */ }
  }

  function syncChips() {
    var sc = $('scopeChips');
    if (sc) [].forEach.call(sc.children, function (c) {
      c.classList.toggle('active', c.dataset.scope === state.scope);
    });
    var rc = $('rangeChips');
    if (rc) [].forEach.call(rc.children, function (c) {
      c.classList.toggle('active', !state.custom && c.dataset.preset === state.preset);
    });
  }

  /* ---------------- 工具 ---------------- */
  function money(v) {
    return (Number(v) || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function moneyShort(v) {
    v = Number(v) || 0;
    if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + '亿';
    // 小于 1 万也带单位：直接甩「6911」旁边挨着「27.5万」会看不出是什么
    if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(1) + '万';
    if (Math.abs(v) >= 1e3) return (v / 1e3).toFixed(1) + '千';
    return v.toFixed(0) + '元';
  }
  function int(v) { return (Number(v) || 0).toLocaleString('zh-CN'); }
  function pct(v, d) { return ((Number(v) || 0) * 100).toFixed(d === undefined ? 1 : d) + '%'; }
  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function toast(msg, isErr) {
    var t = $('toast');
    t.textContent = msg;
    t.className = 'toast show' + (isErr ? ' err' : '');
    clearTimeout(t._h);
    t._h = setTimeout(function () { t.className = 'toast'; }, isErr ? 7000 : 3200);
  }
  function loading(on, msg) {
    $('overlay').classList.toggle('hidden', !on);
    if (msg) $('overlayMsg').textContent = msg;
  }
  function showError(msg) {
    $('errorBox').innerHTML = msg ? '<div class="error">' + esc(msg) + '</div>' : '';
  }

  /* ---------------- 取数 ---------------- */
  function url() {
    var p = '范围=' + encodeURIComponent(state.scope);
    if (state.start || state.end) {
      p += '&start=' + encodeURIComponent(state.start) + '&end=' + encodeURIComponent(state.end);
    } else {
      p += '&时间=' + encodeURIComponent(state.preset);
    }
    if (state.force) { p += '&force=1'; state.force = false; }
    return '/api/data?' + p;
  }

  function load(opts) {
    opts = opts || {};
    if (STATIC) {                    // 静态页：直接用嵌好的数据，不请求接口
      state.data = STATIC;
      assignColors(STATIC);
      render();
      loading(false);
      return;
    }
    loading(true, opts.msg || '正在从 ERP 取数…');
    showError('');
    fetch(url())
      .then(function (r) {
        return r.json().then(function (j) {
          if (j && j.needLogin) {          // 访问码失效了，回登录页
            location.reload();
            throw new Error('__relogin__');
          }
          if (!r.ok || j.error) throw new Error(j.error || ('HTTP ' + r.status));
          return j;
        });
      })
      .then(function (j) {
        state.data = j;
        assignColors(j);
        render();
        loading(false);
        if (opts.toast) toast(opts.toast);
      })
      .catch(function (e) {
        if (e.message === '__relogin__') return;   // 已经在跳登录页了，别再弹错
        loading(false);
        showError('取数失败：' + e.message +
          '\n\n排查建议：\n· 能不能打开 ERP 网址（浏览器试一下）\n· config.json 里的账号密码对不对\n· 点「重新抓取」清掉缓存再试');
        toast('取数失败', true);
      });
  }

  function assignColors(d) {
    state.colorOf = {};
    var names = d.stores.map(function (s) { return s.name; });
    var others = Object.keys(d.storeTypes || {}).filter(function (n) { return names.indexOf(n) < 0; });
    names.concat(others).forEach(function (n, i) {
      state.colorOf[n] = PALETTE[i % PALETTE.length];
    });
  }

  /* ---------------- 渲染 ---------------- */
  /* ---------------- 锚点跳转 ----------------
     两个坑：
     1) 浏览器解析 #锚点 时数据还没渲染，元素不存在，滚动会落空
     2) 渲染时 writeHash() 会把 #锚点 覆盖成状态 hash
     所以启动时先把锚点存下来，渲染完再跳。状态 hash 是 k=v 形式，用有没有 = 区分。 */
  function applyHashAnchor() {
    var h = state.anchor;
    if (!h) return;
    var el = null;
    try { el = document.getElementById(decodeURIComponent(h)); } catch (e) { el = null; }
    if (el) setTimeout(function () { el.scrollIntoView({ block: 'start' }); }, 120);
  }

  function render() {
    var d = state.data;
    if (!d) return;
    writeHash();

    $('brandSub').textContent = d.scope === '商场店' ? '三个商场店' : '全部渠道';
    var rangeTxt = (d.range.start || d.range.end)
      ? (d.range.start || '不限') + ' ~ ' + (d.range.end || '不限') : '全部时间';
    $('metaLine').textContent =
      '数据区间 ' + rangeTxt +
      '　|　ERP 合同 ' + int(d.rawCount) + ' 条　|　纳入统计 ' + int(d.totals.count) + ' 条' +
      '　|　抓取于 ' + d.fetchedAt + '　|　口径：合同金额（优惠后）· 签订日期';

    if (!state.start && !state.end) {
      $('dFrom').value = d.range.start || '';
      $('dTo').value = d.range.end || '';
    }

    renderKpis();
    renderToday();
    renderStores();
    renderTrend();
    renderCompare();
    renderGoal();
    renderEveryone();
    renderDetail();
    applyHashAnchor();
  }

  /* ---------------- 同比 / 环比 ---------------- */
  function pctText(p) {
    if (p === null || p === undefined) return '—';
    return (p > 0 ? '+' : '') + (p * 100).toFixed(1) + '%';
  }

  function deltaHtml(d, label, title) {
    if (!d) return '';
    var p = d['百分比'];
    var cls = (p === null || p === undefined) ? 'flat' : (p > 0.0005 ? 'up' : (p < -0.0005 ? 'down' : 'flat'));
    var arrow = cls === 'up' ? '▲' : (cls === 'down' ? '▼' : '—');
    return '<div class="delta ' + cls + '"' + (title ? ' title="' + esc(title) + '"' : '') + '>' +
      '<span class="k">' + esc(label) + '</span>' +
      '<span class="v"><span class="arrow">' + arrow + '</span>' + pctText(p) + '</span>' +
      '<span class="base">基期 ' + moneyShort(d['基期']) + '</span>' +
      '</div>';
  }

  function cellsClass(p) {
    if (p === null || p === undefined) return 'cmp-na';
    if (p > 0.0005) return 'cmp-up';
    if (p < -0.0005) return 'cmp-down';
    return 'cmp-flat';
  }

  // 涨跌用「以 0 为中心的双向条」表示，比纯数字直观
  function dvBar(p) {
    if (p === null || p === undefined) return '<div class="dv"><span class="txt cmp-na">—</span></div>';
    var cls = p > 0.0005 ? 'pos' : (p < -0.0005 ? 'neg' : '');
    var w = Math.min(Math.abs(p) * 100, 50);
    return '<div class="dv">' +
      '<div class="axis"><i class="' + cls + '" style="width:' + w.toFixed(1) + '%"></i></div>' +
      '<span class="txt ' + cellsClass(p) + '">' + pctText(p) + '</span>' +
      '</div>';
  }

  function renderKpis() {
    var d = state.data;
    var t = d.totals;
    var c = d.compare || {};
    var avg = t.count ? t.amount / t.count : 0;

    // 区间太长时「上一等长周期」没有业务含义，KPI 上就不显示环比（逐月表里照常显示）
    var spanDays = 0;
    if (d.range.start && d.range.end) {
      spanDays = (new Date(d.range.end) - new Date(d.range.start)) / 86400000 + 1;
    }
    var momUseful = c['有环比'] && spanDays > 0 && spanDays <= 92;

    var items = [
      {
        hero: true, lbl: '总业绩', val: moneyShort(t.amount), unit: '元',
        sub: '精确 ' + money(t.amount) + ' 元',
        deltas: [
          deltaHtml(t['同比'], '同比', c['同比标签']),
          momUseful ? deltaHtml(t['环比'], '环比', c['环比标签']) : ''
        ]
      },
      {
        lbl: '合同数', val: int(t.count), unit: '份',
        sub: '平均每份 ' + moneyShort(avg) + ' 元',
        deltas: [deltaHtml(t['同比合同数'], '同比', c['同比标签'])]
      },
      { lbl: '销售人数', val: int(t.people), unit: '人', sub: '有业绩记录的人', deltas: [] },
      {
        lbl: '门店数', val: int(t.stores), unit: '个',
        sub: d.scope === '商场店' ? '商场店' : '含其他渠道', deltas: []
      }
    ];

    // 有任务就加一张「任务达成」卡
    var tk = d['任务'];
    if (tk && tk['标准']) {
      var pr = tk['完成率标准'];
      var lvl = pr >= 1 ? 'up' : (tk['最低'] && tk['业绩'] >= tk['最低'] ? 'flat' : 'down');
      items.push({
        hero: true,
        lbl: '任务达成',
        val: (pr * 100).toFixed(1), unit: '%',
        sub: '标准任务 ' + moneyShort(tk['标准']) + ' 元 / ' + (tk['月数'] || 1) + ' 个月',
        deltas: [
          '<div class="delta ' + lvl + '"><span class="k">最低任务</span>' +
          '<span class="v">' + moneyShort(tk['最低'] || 0) + '</span>' +
          '<span class="base">' + (tk['完成率最低'] !== null
            ? (tk['完成率最低'] * 100).toFixed(0) + '%' : '—') + '</span></div>'
        ]
      });
    }

    $('kpis').innerHTML = items.map(function (it) {
      var dl = (it.deltas || []).filter(Boolean);
      return '<div class="kpi' + (it.hero ? ' hero' : '') + '">' +
        '<div class="lbl">' + it.lbl + '</div>' +
        '<div class="val">' + it.val + (it.unit ? '<span class="unit">' + it.unit + '</span>' : '') + '</div>' +
        '<div class="sub">' + it.sub + '</div>' +
        (dl.length ? '<div class="deltas">' + dl.join('') + '</div>' : '') +
        '</div>';
    }).join('');
  }

  /* ---------------- 逐月同比环比 ---------------- */
  function renderCompare() {
    var d = state.data;
    var rows = d.trend || [];
    var c = d.compare || {};
    $('cmpHint').innerHTML = '环比 = 与上一个月比　·　同比 = 与去年同月比' +
      (c['同比标签'] ? '　|　' + esc(c['同比标签']) : '');

    if (!rows.length) {
      $('cmpTable').innerHTML = '<tbody><tr><td class="empty">没有数据</td></tr></tbody>';
      return;
    }
    var maxTotal = Math.max.apply(null, rows.map(function (x) { return x.total; })) || 1;
    var curSum = 0, yoySum = 0, hasYoy = false;
    rows.forEach(function (m) {
      curSum += m.total;
      yoySum += (m.lastYear || 0);
      if (m.lastYear > 0) hasYoy = true;
    });

    var body = rows.map(function (m) {
      var mo = m['环比'], yo = m['同比'];
      var ly = m.lastYear || 0;
      // 去年这个月还没有这家店（三家商场店 2025-05 才开业）—— 标成「新增」，
      // 别显示成 0.00 让人以为是数据缺失
      var noBase = ly === 0 && m.total > 0;
      var yoyCell = noBase
        ? '<td class="num" style="color:var(--red);font-weight:700" title="去年同月无经营">新增</td>'
        : '<td>' + dvBar(yo ? yo['百分比'] : null) + '</td>';
      return '<tr>' +
        '<td><b>' + esc(m.month) + '</b></td>' +
        '<td class="num">' + money(m.total) + '</td>' +
        '<td>' + dvBar(mo ? mo['百分比'] : null) + '</td>' +
        '<td class="num" style="color:var(--muted)">' + (mo ? money(mo['基期']) : '—') + '</td>' +
        '<td class="num" style="color:var(--muted)">' + (noBase ? '无经营' : money(ly)) + '</td>' +
        yoyCell +
        '</tr>';
    }).join('');

    var totalYoy = hasYoy && yoySum > 0 ? (curSum - yoySum) / yoySum : null;
    body += '<tr class="row-first">' +
      '<td><b>合计</b></td>' +
      '<td class="num"><b>' + money(curSum) + '</b></td>' +
      '<td></td><td class="num">—</td>' +
      '<td class="num"><b>' + money(yoySum) + '</b></td>' +
      '<td class="num ' + cellsClass(totalYoy) + '"><b>' + pctText(totalYoy) + '</b></td></tr>';

    $('cmpTable').innerHTML =
      '<thead><tr><th>月份</th><th class="num">本月业绩</th>' +
      '<th class="num">环比</th><th class="num">上月</th>' +
      '<th class="num">去年同期</th><th class="num">同比</th></tr></thead>' +
      '<tbody>' + body + '</tbody>';
  }

  function donut(share, color) {
    var S = 66, r = 27, c = 2 * Math.PI * r, on = c * Math.max(0, Math.min(1, share));
    // 小占比保留一位小数，避免 0.2% 被显示成 0%
    var label = share > 0 && share < 0.1 ? (share * 100).toFixed(1) + '%' : pct(share, 0);
    return '<div class="donut"><svg width="' + S + '" height="' + S + '" viewBox="0 0 ' + S + ' ' + S + '">' +
      '<circle cx="33" cy="33" r="' + r + '" fill="none" stroke="#F0F1F3" stroke-width="6"/>' +
      '<circle cx="33" cy="33" r="' + r + '" fill="none" stroke="' + color + '" stroke-width="6" ' +
      'stroke-dasharray="' + on + ' ' + (c - on) + '"/>' +
      '</svg><div class="pct">' + label + '</div></div>';
  }

  // 迷你趋势线：一眼看出走势，不用读数字
  function sparkline(values, color, w, h) {
    w = w || 132; h = h || 30;
    var vals = values.length ? values : [0];
    var max = Math.max.apply(null, vals) || 1;
    var step = vals.length > 1 ? w / (vals.length - 1) : w;
    var pts = vals.map(function (v, i) {
      return [i * step, h - (v / max) * (h - 5) - 2.5];
    });
    var line = pts.map(function (p, i) {
      return (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1);
    }).join(' ');
    var area = line + ' L' + w.toFixed(1) + ' ' + h + ' L0 ' + h + ' Z';
    var last = pts[pts.length - 1];
    return '<svg class="spark" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '">' +
      '<path d="' + area + '" fill="' + color + '" opacity=".08"/>' +
      '<path d="' + line + '" fill="none" stroke="' + color + '" stroke-width="1.6" ' +
        'stroke-linejoin="round" stroke-linecap="round"/>' +
      '<circle cx="' + last[0].toFixed(1) + '" cy="' + last[1].toFixed(1) + '" r="2.6" fill="' + color + '"/>' +
      '</svg>';
  }

  // 达标进度条：0 → 标准任务，黑刻度线是最低任务
  function taskBlock(s) {
    var t = s['任务'];
    if (!t || (!t['标准'] && !t['最低'])) return '';
    var std = t['标准'], lo = t['最低'];
    var base = std || lo;                      // 没有标准任务就拿最低当满格
    var pctVal = s.amount / base;
    var lvl = 'low';
    if (std) {
      if (pctVal >= 1) lvl = 'ok';
      else if (lo && s.amount >= lo) lvl = 'mid';
    } else {
      lvl = pctVal >= 1 ? 'ok' : 'low';      // 只设了最低任务时，满格=达标
    }
    var w = Math.min(pctVal * 100, 100);
    var marker = (std && lo) ? '<span class="task-min" style="left:' +
      (lo / std * 100).toFixed(1) + '%" title="最低任务 ' + moneyShort(lo) + ' 元"></span>' : '';
    var flag = '';
    if (lo) {
      flag = s.amount >= lo
        ? '<span class="flag ok">✔ 已达最低</span>'
        : '<span class="flag no">✘ 未达最低</span>';
    }
    return '<div class="task">' +
      '<div class="task-head">' +
        '<span>' + (std ? '标准任务 <b>' + moneyShort(std) + '</b> 元' : '仅设最低任务') + '</span>' +
        '<span class="task-pct ' + lvl + '">' + pct(pctVal, 1) + '</span>' +
      '</div>' +
      '<div class="task-bar"><i class="' + lvl + '" style="width:' + w.toFixed(1) + '%"></i>' + marker + '</div>' +
      '<div class="task-foot">' +
        '<span>' + (lo ? '最低任务 ' + moneyShort(lo) + ' 元' : '未设最低任务') +
          '　·　' + (t['月数'] || 1) + ' 个月</span>' +
        flag +
      '</div>' +
    '</div>';
  }

  function renderStores() {
    var d = state.data;
    var total = d.totals.amount || 1;
    if (!d.stores.length) {
      $('stores').innerHTML = '<div class="empty">这个时间范围内没有数据</div>';
      return;
    }
    $('stores').innerHTML = d.stores.map(function (s) {
      var color = state.colorOf[s.name] || '#14161A';
      var champ = s.staff.filter(function (x) { return x.count > 0; })[0];
      var yo = s['同比'];
      var ly = yo ? yo['基期'] : 0;
      var noBase = ly === 0 && s.amount > 0;
      var yoTxt = noBase ? '<span style="color:var(--red);font-weight:700">新增</span>'
        : (yo ? '<span class="' + cellsClass(yo['百分比']) + '">' + pctText(yo['百分比']) + '</span>'
              : '<span class="cmp-na">—</span>');
      return '<div class="store">' +
        '<div class="store-head">' +
          donut(s.amount / total, color) +
          '<div style="flex:1;min-width:0">' +
            '<div><span class="store-name">' + esc(s.name) + '</span> ' +
              '<span class="store-tag' + (s.type === '商场店' ? '' : ' other') + '">' + esc(s.type) + '</span></div>' +
            '<div class="store-champ">销冠 <b>' + esc(champ ? champ.name : '—') + '</b>' +
              (champ ? '（' + moneyShort(champ.amount) + ' 元）' : '') + '</div>' +
            '<div class="store-nums">' +
              '<div class="store-num"><div class="n">' + moneyShort(s.amount) + '</div><div class="t">业绩（元）</div></div>' +
              '<div class="store-num"><div class="n">' + int(s.count) + '</div><div class="t">合同数</div></div>' +
              '<div class="store-num"><div class="n">' + int(s.people) + '</div><div class="t">销售人数</div></div>' +
              '<div class="store-num"><div class="n">' + yoTxt + '</div><div class="t">同比 YoY</div></div>' +
            '</div>' +
            '<div class="store-spark">' +
              sparkline(d.trend.map(function (t) { return (t.byStore || {})[s.name] || 0; }), color) +
              '<span>月度走势</span>' +
            '</div>' +
            taskBlock(s) +
          '</div>' +
        '</div>' +
      '</div>';
    }).join('');
  }

  /* ---------------- 月度走势 ---------------- */
  function renderTrend() {
    // 这一块（月度走势按人）已从页面删掉 —— 看「本月」时只有一根柱子，没意义。
    // 留个守卫，免得再调用时报 null。
    if (!$('trendWrap') || !$('trendLegend')) return;
    var d = state.data;
    var months = d.trend || [];
    if (!months.length) {
      $('trendWrap').innerHTML = '<div class="empty">没有月度数据</div>';
      $('trendLegend').innerHTML = '';
      return;
    }
    // 月度走势按「人」拆解：堆叠顺序固定按区间总业绩降序，
    // 这样同一个人每根柱子里的位置和颜色都一样，方便横向对比。
    var names = (d.personOrder && d.personOrder.length)
      ? d.personOrder.slice()
      : d.everyone.filter(function (p) { return p.count > 0; }).map(function (p) { return p.name; });
    var hasLast = months.some(function (m) { return (m.lastYear || 0) > 0; });

    // 图幅：7 段堆叠 + 10 个月，矮了就看不清。加高到 430，柱子铺开到约 3/4 步长。
    var W = 1200, H = 430, padL = 78, padR = 22, padT = 52, padB = 52;
    var iw = W - padL - padR, ih = H - padT - padB;
    var max = Math.max.apply(null, months.map(function (m) {
      return Math.max(m.total, m.lastYear || 0);
    })) || 1;
    max = niceMax(max);

    var step = iw / months.length;
    var bw = Math.min(96, step * 0.78);                     // 堆叠柱宽：铺开

    var svg = ['<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">'];
    for (var g = 0; g <= 4; g++) {
      var y = padT + ih - (ih * g / 4);
      svg.push('<line x1="' + padL + '" y1="' + y + '" x2="' + (W - padR) + '" y2="' + y +
        '" stroke="#EFF1F4" stroke-width="1"/>');
      svg.push('<text x="' + (padL - 12) + '" y="' + (y + 4) + '" text-anchor="end" font-size="12" fill="#8C929B">' +
        moneyShort(max * g / 4) + '</text>');
    }

    var baseY = padT + ih;
    months.forEach(function (m, i) {
      var groupW = bw;
      var x0 = padL + step * i + (step - groupW) / 2;

      var acc = 0;
      names.forEach(function (n) {
        var v = (m.byPerson || {})[n] || 0;
        if (!v) return;
        var h = ih * v / max;
        // 每段加一圈白边，段与段之间才分得开（同色系相邻时尤其重要）
        svg.push('<rect class="bar-rect" x="' + x0.toFixed(1) + '" y="' + (baseY - acc - h).toFixed(1) +
          '" width="' + bw.toFixed(1) + '" height="' + Math.max(h, 1).toFixed(1) +
          '" fill="' + personColor(names.indexOf(n)) + '" stroke="#FFFFFF" stroke-width="1">' +
          '<title>' + esc(m.month) + '　' + esc(n) + '：' + money(v) + ' 元　（占该月 ' +
          (m.total ? (v / m.total * 100).toFixed(1) : '0') + '%）</title></rect>');
        acc += h;
      });

      if (hasLast && (m.lastYear || 0) > 0) {
        // 去年同期画成一条水平基准线（参考值的标准画法），比空心柱干净
        var lv = m.lastYear;
        var ly = baseY - ih * lv / max;
        svg.push('<line x1="' + (x0 - 5).toFixed(1) + '" y1="' + ly.toFixed(1) +
          '" x2="' + (x0 + bw + 5).toFixed(1) + '" y2="' + ly.toFixed(1) +
          '" stroke="#A9AFB8" stroke-width="1.5" stroke-dasharray="4 3">' +
          '<title>' + esc(m.lastYearMonth || '') + '　去年同期：' + money(lv) + ' 元</title></line>');
        svg.push('<line x1="' + (x0 - 5).toFixed(1) + '" y1="' + (ly - 4).toFixed(1) +
          '" x2="' + (x0 - 5).toFixed(1) + '" y2="' + (ly + 4).toFixed(1) +
          '" stroke="#A9AFB8" stroke-width="1.5"/>');
        svg.push('<line x1="' + (x0 + bw + 5).toFixed(1) + '" y1="' + (ly - 4).toFixed(1) +
          '" x2="' + (x0 + bw + 5).toFixed(1) + '" y2="' + (ly + 4).toFixed(1) +
          '" stroke="#A9AFB8" stroke-width="1.5"/>');
      }

      // 柱顶标总额，下面紧跟同比 —— 光看颜色不知道这个月做了多少
      var cx = x0 + groupW / 2;
      var topY = baseY - acc;
      svg.push('<text x="' + cx.toFixed(1) + '" y="' + (topY - 26).toFixed(1) +
        '" text-anchor="middle" font-size="12.5" font-weight="700" fill="#14161A">' +
        moneyShort(m.total) + '</text>');
      if (m['同比'] && m['同比']['基期'] > 0) {
        var p = m['同比']['百分比'];
        var col = p > 0 ? '#0E7A45' : (p < 0 ? '#D90429' : '#8C929B');
        var arw = p > 0 ? '▲' : (p < 0 ? '▼' : '');
        svg.push('<text x="' + cx.toFixed(1) + '" y="' + (topY - 11).toFixed(1) +
          '" text-anchor="middle" font-size="11" font-weight="700" fill="' + col + '">' +
          arw + (Math.abs(p) * 100).toFixed(0) + '%</text>');
      }

      svg.push('<text x="' + (padL + step * i + step / 2).toFixed(1) + '" y="' + (H - 18) +
        '" text-anchor="middle" font-size="12" font-weight="600" fill="#5A6068">' +
        esc(m.month.slice(2)) + '</text>');
    });
    // 底部基线
    svg.push('<line x1="' + padL + '" y1="' + baseY + '" x2="' + (W - padR) + '" y2="' + baseY +
      '" stroke="#D5D9DE" stroke-width="1.5"/>');
    svg.push('</svg>');
    $('trendWrap').innerHTML = svg.join('');

    $('trendLegend').innerHTML =
      names.map(function (n, i) {
        return '<span><i style="background:' + personColor(i) + '"></i>' + esc(n) + '</span>';
      }).join('') +
      (hasLast ? '<span><i class="dash"></i>去年同期</span>' : '') +
      '<span style="margin-left:auto;color:var(--muted)">每根柱子里按人堆叠（从下往上＝业绩降序）　·　柱顶 ▲▼ 为该月同比　·　单位：元</span>';
  }

  function niceMax(v) {
    var p = Math.pow(10, Math.floor(Math.log10(v)));
    var n = v / p;
    var m = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
    return m * p;
  }

  /* ---------------- 销售排名（横向条形，一眼看完） ---------------- */
  function renderEveryone() {
    var d = state.data;
    var list = d.everyone.filter(function (p) { return p.count > 0; });
    $('everyoneHint').textContent = list.length + ' 人 · 合计 ' + money(d.totals.amount) + ' 元';
    if (!list.length) {
      $('rankList').innerHTML = '<div class="empty">没有数据</div>';
      return;
    }
    var max = list[0].amount || 1;      // everyone 已按金额降序
    $('rankList').innerHTML = list.map(function (p, i) {
      var rank = i + 1;
      var yo = p['同比'];
      var ly = yo ? yo['基期'] : 0;
      var noBase = ly === 0 && p.amount > 0;
      var yoTxt, yoyCls;
      if (noBase) { yoTxt = '新增'; yoyCls = 'cmp-down'; }
      else if (!yo || yo['百分比'] === null) { yoTxt = '—'; yoyCls = 'cmp-na'; }
      else { yoTxt = pctText(yo['百分比']); yoyCls = cellsClass(yo['百分比']); }
      return '<div class="rankrow' + (rank <= 3 ? ' top' + rank : '') + '">' +
        '<div class="rk">' + rank + '</div>' +
        '<div class="who">' +
          '<b data-person="' + esc(p.name) + '" data-store="' + esc(p.store) + '">' + esc(p.name) + '</b>' +
          '<span>' + esc(p.store) + '</span>' +
        '</div>' +
        '<div class="track"><i style="width:' + Math.max(p.amount / max * 100, 1.5).toFixed(1) + '%"></i></div>' +
        '<div class="amt">' + money(p.amount) + '</div>' +
        '<div class="cnt">' + int(p.count) + ' 单</div>' +
        '<div class="yoy ' + yoyCls + '">' + yoTxt + '</div>' +
      '</div>';
    }).join('');
  }

  /* ---------------- 目标拆解：店 → 人 → 型号 ---------------- */
  // 把「目标金额」按当前实际销售的系列结构，换算成每个系列要卖几台
  function unitsFor(target, series) {
    if (!target || !series || !series.length) return [];
    return series.map(function (r) {
      var amt = target * (r['占比'] || 0);
      return {
        '系列': r['系列'],
        '金额': amt,
        '台数': r['均价'] ? amt / r['均价'] : 0,
        '均价': r['均价']
      };
    }).filter(function (x) { return x['台数'] >= 0.05; })
      .sort(function (a, b) { return b['金额'] - a['金额']; });   // 按金额（＝实际结构）排，不按台数
  }

  // 某个人的强制型号 = 「所有人」通用要求 + 该人的额外要求（叠加）
  function forcedFor(name) {
    var f = state.data['强制型号'] || {};
    var out = {};
    var all = f['所有人'] || {};
    Object.keys(all).forEach(function (k) { out[k] = all[k]; });
    var mine = (f['按人'] || {})[name] || {};
    Object.keys(mine).forEach(function (k) {
      out[k] = (out[k] || 0) + mine[k];        // 叠加，不是覆盖
    });
    return out;
  }

  // 把「缺口里的相机部分」按**在产型号**拆成**整数台数**。
  // 为什么必须整数：0.9 台、0.3 台这种数门店没法执行，店长看了也没法用。
  //
  // 算法分三步：
  //   1. 先按实际结构排（各自向下取整）
  //   2. **追加**强制型号 —— 是在结构之上 +N 台，不是"至少 N 台"
  //      （用"至少"的话，结构里本来就有 1 台 SL3 的人会一台都不多，
  //        高帅的 M11-P 就被这样吸收掉了，追加等于没加）
  //   3. 余钱按小数部分补台；超了就从「台数最多、单价最低」的非追加型号里砍
  function planCameras(target, models, extra) {
    var live = (models || []).filter(function (m) {
      return m['在产'] && m['均价'] > 0;
    });
    if (!target || !live.length) return { list: [], amount: 0, target: target || 0 };

    var byName = {};
    live.forEach(function (m) { byName[m['型号']] = m; });
    extra = extra || {};

    var sumShare = live.reduce(function (a, m) { return a + (m['占相机'] || 0); }, 0) || 1;
    var items = live.map(function (m) {
      var amt = target * (m['占相机'] || 0) / sumShare;
      var ideal = amt / m['均价'];
      return {
        '型号': m['型号'], '系列': m['系列'], '均价': m['均价'],
        '台数': Math.floor(ideal), '小数': ideal - Math.floor(ideal),
        '强制': false
      };
    });
    var itemOf = {};
    items.forEach(function (x) { itemOf[x['型号']] = x; });

    function spent() {
      return items.reduce(function (a, x) { return a + x['台数'] * x['均价']; }, 0);
    }

    // ---- 第 1 步：先把「按结构 + 余钱补台」的完整方案排出来 ----
    // 必须在追加之前排完。先追加的话，补台时那台会被强制占位吃掉，
    // 净增变成 0（实测：高帅结构里补出来的 1 台 M11-P 就这样没了）。
    var guard0 = 0;
    while (guard0++ < 500) {
      var rest0 = target - spent();
      if (rest0 <= 0) break;
      var c0 = items
        .filter(function (x) { return x['均价'] <= rest0 + 0.01; })
        .sort(function (a, b) { return b['小数'] - a['小数']; })[0];
      if (!c0) break;
      c0['台数'] += 1;
      c0['小数'] = 0;
    }

    // ---- 第 2 步：在完整方案之上**追加** ----
    var missing = [];
    Object.keys(extra).forEach(function (name) {
      var x = itemOf[name];
      if (!x) { missing.push(name); return; }
      x['台数'] += extra[name];
      x['强制'] = true;
    });

    // ---- 第 3 步：追加后超额，砍到最接近目标 ----
    // 不是"砍到不超为止"，而是"砍到偏差最小" ——
    // 否则会出现这种情况：超 38,854 元，但剩下的型号每台 59,600 元，
    // 一刀砍下去变欠 20,746 元，明明更接近却因为"不能超"而砍不动。
    var cut = [];
    var guard2 = 0;
    while (guard2++ < 500) {
      var dev = spent() - target;
      if (Math.abs(dev) <= 0.01) break;
      var best = null, bestAbs = Math.abs(dev);
      items.forEach(function (x) {
        if (x['强制'] || x['台数'] <= 0) return;
        var after = Math.abs(dev - x['均价']);
        if (after < bestAbs - 0.01) { bestAbs = after; best = x; }
      });
      if (!best) break;
      best['台数'] -= 1;
      cut.push(best['型号']);
    }
    var finalDev = spent() - target;

    var list = items.filter(function (x) { return x['台数'] > 0; })
      .map(function (x) {
        x['金额'] = x['台数'] * x['均价'];
        return x;
      })
      .sort(function (a, b) { return b['金额'] - a['金额']; });

    var uniq = [];
    cut.forEach(function (v) { if (uniq.indexOf(v) < 0) uniq.push(v); });

    return {
      list: list,
      amount: list.reduce(function (a, x) { return a + x['金额']; }, 0),
      target: target, cut: uniq, missing: missing,
      // 还是超 → 强制指标本身就塞不下，界面必须说出来
      over: finalDev > 0.01 ? finalDev : 0
    };
  }

  function unitsBrief(list, n) {
    if (!list.length) return '<span class="cmp-na">—</span>';
    var show = n && list.length > n ? list.slice(0, n) : list;
    return show.map(function (u) {
      // 整数台 —— 没有 0.几 台；强制的加个星标
      return '<span class="mu' + (u['强制'] ? ' mu-forced' : '') + '">' +
        (u['强制'] ? '★' : '') + '<b>' + esc(u['型号']) + '</b> ' +
        u['台数'] + ' 台<i>' + moneyShort(u['金额']) + '</i></span>';
    }).join('');
  }

  // 悬停看完整明细（含单价、金额），并把金额合计和缺口对账
  function unitsFull(list, target, plan) {
    var lines = list.map(function (u) {
      return (u['强制'] ? '★ ' : '') + u['型号'] + '（' + u['系列'] + '）　' +
        u['台数'] + ' 台 × ' + money(u['均价']) + ' = ' + money(u['金额']) + ' 元' +
        (u['强制'] ? '　【强制指标】' : '');
    });
    var sum = list.reduce(function (a, x) { return a + x['金额']; }, 0);
    if (target) {
      lines.push('');
      lines.push('——————————————————');
      lines.push('相机金额合计：' + money(sum) + ' 元');
      lines.push('相机应补缺口：' + money(target) + ' 元');
      var d2 = sum - target;
      lines.push((d2 > 0 ? '超出' : '差　') + '　　　　：' + money(Math.abs(d2)) + ' 元'
        + (Math.abs(d2) < 1 ? '（对得上）' : ''));
      if (plan && plan.cut && plan.cut.length) {
        lines.push('');
        lines.push('为了塞进强制指标，从这些型号里减了：' + plan.cut.join('、'));
      }
      if (plan && plan.missing && plan.missing.length) {
        lines.push('⚠ 强制型号不在在产清单里：' + plan.missing.join('、'));
      }
      if (plan && plan.over) {
        lines.push('');
        lines.push('⚠ 光强制指标就超了 ' + money(plan.over) +
          ' 元 —— 这个月的缺口不够塞，其余型号一台都排不下。');
      }
    }
    return lines.join('\n');
  }

  // 把「目标金额」按系列结构换算成件数（含镜头配件，覆盖 100%）
  function unitsFor(target, series) {
    if (!target || !series || !series.length) return [];
    return series.map(function (r) {
      var amt = target * (r['占比'] || 0);
      return {
        '系列': r['系列'],
        '金额': amt,
        '占比': r['占比'] || 0,
        '台数': r['均价'] ? amt / r['均价'] : 0,
        '均价': r['均价']
      };
    }).sort(function (a, b) { return b['金额'] - a['金额']; });
  }

  /* ---------------- 今日销售 ---------------- */
  // 管理层每天最想先看的两件事：今天做了多少钱、卖了什么。
  // 金额用合同金额（准）；产品名只能从产品明细里按日期捞（合同明细里没有产品名）。
  function renderToday() {
    var box = $('todayCard');
    if (!box) return;
    var d = state.data || {};
    var td = d['今日'];
    if (!td) { box.style.display = 'none'; return; }
    box.style.display = '';

    var wd = '';
    try {
      var dt = new Date(td['日期'] + 'T00:00:00');
      wd = '周' + '日一二三四五六'.charAt(dt.getDay());
    } catch (e) {}

    var items = (td['明细'] || []).slice(0, 12);
    // 「今日销售」要跟着搜索框和人名点选走 —— 点姜帆时只剩姜帆的。
    // 之前这里没过滤，点谁都是全店的，看着像筛选失效。
    var fq = (state.q || '').trim();
    var fstore = state.filterStore || '';
    var recsAll = (d.records || []).filter(function (r) {
      return String(r.date).slice(0, 10) === td['日期'];
    });
    var recsHit = recsAll.filter(function (r) {
      if (fq && (r.person || '').indexOf(fq) < 0) return false;
      if (fstore && (r.store || '') !== fstore) return false;
      return true;
    });
    var filtered = !!(fq || fstore);
    if (filtered) {
      items = items.filter(function (it) {
        if (fq && (it['销售员'] || '').indexOf(fq) < 0) return false;
        if (fstore && (it['门店'] || '') !== fstore) return false;
        return true;
      });
    }
    var amtShown = filtered
      ? recsHit.reduce(function (a, r) { return a + (Number(r.amount) || 0); }, 0)
      : (td['金额'] || 0);
    var cntShown = filtered ? recsHit.length : (td['合同数'] || 0);
    var body;
    if (items.length) {
      body = '<div class="today-list">' + items.map(function (it) {
        // 服务/维修没有"台"的概念，别写成"维修费用 1 台"
        var noUnit = (it['品类'] === '服务');
        var qty = it['数量'] ? ((noUnit ? '×' : '') +
          (Math.round(it['数量'] * 100) / 100) + (noUnit ? '' : ' 台')) : '';
        return '<div class="today-row">' +
          '<span class="t-who">' + esc(it['销售员'] || '') + '</span>' +
          '<span class="t-store">' + esc(it['门店'] || '') + '</span>' +
          '<span class="t-what">' + esc(it['型号'] || it['品类'] || '') +
            (qty ? '<i>' + esc(qty) + '</i>' : '') + '</span>' +
          '<span class="t-amt">' + money(it['金额']) + '</span>' +
        '</div>';
      }).join('') + '</div>';
    } else {
      // 产品明细缓存是按天增量抓的，今天的新合同可能还没抓到。
      // 这时退回合同明细 —— 客户备注里一般写了买的什么（"二手Q2 X""M11-P 银"）。
      var recs = recsHit.slice(0, 12);
      if (!recs.length) {
        body = '<div class="today-empty">' + (filtered ? esc(fq || fstore) + ' 今天还没有成交记录' : '今天还没有成交记录') + '</div>';
      } else {
        body = '<div class="today-list">' + recs.map(function (r) {
          return '<div class="today-row">' +
            '<span class="t-who">' + esc(r.person || '') + '</span>' +
            '<span class="t-store">' + esc(r.store || '') + '</span>' +
            '<span class="t-what">' + esc(r.customer || r.title || '') + '</span>' +
            '<span class="t-amt">' + money(r.amount) + '</span>' +
          '</div>';
        }).join('') + '</div>';
      }
    }

    box.innerHTML =
      '<div class="today-head">' +
        '<div>' +
          '<div class="t-label">今日销售　TODAY</div>' +
          '<div class="t-date">' + esc(td['日期'] || '') + '　' + wd +
            '　·　' + cntShown + ' 份合同' +
            (filtered ? '　·　' + esc(fq || fstore) : '') + '</div>' +
        '</div>' +
        '<div class="t-total">' + moneyShort(amtShown) + ' 元</div>' +
      '</div>' + body;
  }

  function renderGoal() {
    var d = state.data;
    var tk = d['任务'];
    var series = d['系列均价'] || [];
    var models = d['相机型号'] || [];
    // 相机占比用后端算好的（同一个基准区间内的比例），供提示文字用
    var camShare = d['相机占比'] || 0;
    // 产品明细是本地缓存，会过期（新签的合同还没抓）。过期时必须让人看出来，
    // 否则型号拆解会静默少算一截。
    function covText() {
      var cached = d['产品缓存合同数'] || 0;
      var now = (d.totals || {}).count || 0;
      var ref = d['型号基准区间'];
      var refTxt = (ref && ref.start) ? '　·　型号结构取 ' + ref.start + ' ~ ' + ref.end : '';
      if (!cached || !now) return refTxt;
      if (cached >= now) return '　·　产品明细覆盖 ' + cached + '/' + now + ' 份合同' + refTxt;
      return '　·　⚠ 产品明细只覆盖 ' + cached + '/' + now + ' 份合同，' +
        (now - cached) + ' 份未算进来，请跑一次「抓取产品明细.bat」刷新' + refTxt;
    }
    var rows = [];
    (d.stores || []).forEach(function (s) {
      (s.staff || []).forEach(function (p) {
        // 只要定了目标就列出来，哪怕这个区间一单没开。
        // 之前还有 p.count > 0 的限制，结果本月没开单的人目标整个消失，
        // 店长会以为他没指标。
        if (p['目标'] !== null && p['目标'] !== undefined) {
          rows.push({ store: s.name, p: p });
        }
      });
    });

    // 时间进度（提示文字用）
    var timePct = ((d['时间进度'] || {})['百分比']) || 0;

    if (!tk || !rows.length) {
      $('goalTable').innerHTML = '<tbody><tr><td class="empty">没有配置门店目标</td></tr></tbody>';
      $('goalHint').textContent = '';
      $('goalMode').textContent = '';
      return;
    }

    // 目标按整月算（看 10-01~10-16 就是 1 个月的量），
    // 时间进度按实际天数算 —— 两个数不一样，要说清楚，
    // 否则销售看到"目标 80万 / 过了 53%"会以为目标被打了折。
    var tp = d['时间进度'] || {};
    var tpTxt = '';
    if (tp['百分比'] !== null && tp['百分比'] !== undefined) {
      tpTxt = '　·　时间进度 ' + (tp['百分比'] * 100).toFixed(0) + '%' +
        '（实际 ' + tp['实际月数'] + ' 个月 / 目标按 ' + tp['目标月数'] + ' 个整月）';
    }
    $('goalHint').textContent = rows.length + ' 人 · 合计目标 ' + money(tk['标准']) + ' 元 / ' +
      (tk['月数'] || 1) + ' 个整月' + tpTxt;
    $('goalMode').textContent = '拆解方式：' + (tk['拆解方式'] || '平均') +
      '　·　门店月目标 × ' + (tk['月数'] || 1) + ' 个整月';

    $('goalTable').innerHTML =
      '<thead><tr><th>门店</th><th>销售员</th><th class="num">目标</th><th class="num">已完成</th>' +
      '<th style="width:190px">完成率</th><th class="num">差额</th>' +
      '<th>要卖的相机型号（按当前结构）</th></tr></thead><tbody>' +
      rows.map(function (r) {
        var p = r.p;
        var rate = p['目标完成率'];
        // 完成率是 0~100% 的进度，不是涨跌，用普通进度条（不要用双向条）
        var col = rate >= 1 ? 'var(--up)' : (rate >= 0.8 ? '#C77700' : 'var(--down)');
        // 达成状态只用「已达成 / 未达成」两个中性词。
        // 不要用「落后」「垫底」这类评价性说法 —— 这个页面会给店员看。
        var done = rate >= 1;
        var gap = p['目标差额'];
        var gapTxt = gap <= 0
          ? '<span class="cmp-up">超额 ' + money(Math.abs(gap)) + '</span>'
          : '<span class="cmp-down">还差 ' + money(gap) + '</span>';
        // 只拆**徕卡在产相机**，而且必须是**整数台**。
        // 缺口里相机那部分 = 缺口 × 相机占比。
        var camGap = (gap > 0 ? gap : p['目标']) * camShare;
        var plan = planCameras(camGap, models, forcedFor(p.name));
        var units = plan.list;
        var title = gap > 0 ? unitsFull(units, camGap, plan) : '目标已完成';
        return '<tr>' +
          '<td>' + esc(r.store) + '</td>' +
          '<td><b>' + esc(p.name) + '</b></td>' +
          '<td class="num">' + money(p['目标']) + '</td>' +
          '<td class="num">' + money(p.amount) + '</td>' +
          '<td><div style="display:flex;align-items:center;gap:9px">' +
            '<div class="bar" style="flex:1"><i style="width:' +
            Math.min(rate * 100, 100).toFixed(1) + '%;background:' + col + '"></i></div>' +
            '<span style="font-size:12.5px;font-weight:700;color:' + col +
            ';min-width:52px;text-align:right">' + (rate * 100).toFixed(1) + '%</span>' +
            '<span class="st-badge ' + (done ? 'ok' : 'todo') + '">' +
              (done ? '已达成' : '未达成') + '</span>' +
          '</div></td>' +
          '<td class="num">' + gapTxt + '</td>' +
          '<td class="units" title="' + esc(title) + '">' +
            (gap > 0 ? unitsBrief(units, 0) : '<span class="cmp-up">已完成</span>') +
          '</td>' +
        '</tr>';
      }).join('') + '</tbody>';

    var nDone = 0;
    rows.forEach(function (r) { if ((r.p['目标完成率'] || 0) >= 1) nDone++; });
    $('goalHint').innerHTML = esc(rows.length + ' 人 · 合计目标 ' + money(tk['标准']) + ' 元 / ' +
      (tk['月数'] || 1) + ' 个整月' + tpTxt) + '　·　' +
      '<span class="st-badge ok">已达成 ' + nDone + ' 人</span>　' +
      '<span class="st-badge todo">未达成 ' + (rows.length - nDone) + ' 人</span>';
    // （原来还有一张「人 × 相机型号」矩阵和一张「相机型号目标」全店表，
    //   已按需求删掉 —— 表太多看着乱。系列口径更粗，门店执行时更好用。）
    // 注意：pm 必须在这里就赋值。下面那张表要用它，
    // 而 var 只提升声明不提升赋值，放后面会读到 undefined。
    var pm = d['人员型号'];

    // ---- 人 × 型号：每人实际卖了哪些系列、各多少 ----
    if (!pm || !pm.length || !series.length) {
      $('personModelTable').innerHTML = '<tbody><tr><td class="empty">' +
        (series.length ? '没有人员型号数据' : '缺产品明细缓存，先跑一次：抓取产品明细.bat') +
        '</td></tr></tbody>';
      $('pmHint').textContent = '';
      return;
    }
    // 列太多会挤：取金额前 9 个系列，其余并成「其他」。
    // 注意分类里本来就有一个叫「其他」的大类，必须把它排除在候选列之外，
    // 否则会出现两个「其他」列。
    // 望远镜 / 拍立得这类小占比系列量少但必须看得见 —— 只按金额截断的话，
    // 卖了一台望远镜会整个消失（占比 0.8%，排第 10），店长会以为没卖。
    var TOPN = 9;
    var ALWAYS = ['望远镜系列', '拍立得系列'];
    var allNames = series.map(function (r) { return r['系列']; });
    var cols = series
      .filter(function (r) { return r['系列'] !== '其他'; })
      .map(function (r) { return r['系列']; })
      .filter(function (n, i, a) { return i < TOPN || ALWAYS.indexOf(n) >= 0; });
    var restName = '其他';
    var goalOf = {};
    rows.forEach(function (r) { goalOf[r.p.name] = r.p; });

    $('pmHint').textContent = pm.length + ' 人 · 显示金额前 ' + TOPN + ' 个系列（望远镜/拍立得必显示），其余并入「其他」';

    $('personModelTable').innerHTML =
      '<thead><tr><th>销售员</th><th>门店</th><th class="num">目标</th>' +
      cols.map(function (c) { return '<th class="num">' + esc(c) + '</th>'; }).join('') +
      '<th class="num">' + restName + '</th>' +
      '<th class="num">实际合计</th><th style="width:120px">完成率</th></tr></thead><tbody>' +
      pm.map(function (r) {
        var restQ = 0, restM = 0;
        Object.keys(r['系列']).forEach(function (k) {
          if (cols.indexOf(k) < 0) { restQ += r['系列'][k]['数量']; restM += r['系列'][k]['金额']; }
        });
        var g = goalOf[r['销售员']];
        var goal = g && g['目标'] != null ? g['目标'] : null;
        var rate = goal ? r['合计金额'] / goal : null;
        var col = rate == null ? 'var(--muted)'
          : (rate >= 1 ? 'var(--up)' : (rate >= 0.8 ? '#C77700' : 'var(--down)'));

        function cell(q, m) {
          if (!q) return '<td class="num pm-cell pm-zero">—</td>';
          return '<td class="num pm-cell" title="' + money(m) + ' 元">' +
            '<b>' + (q % 1 === 0 ? q : q.toFixed(1)) + '</b> 台' +
            '<span>' + moneyShort(m) + '</span></td>';
        }

        return '<tr>' +
          '<td><b>' + esc(r['销售员']) + '</b></td>' +
          '<td style="color:var(--muted)">' + esc(r['门店']) + '</td>' +
          '<td class="num">' + (goal != null ? money(goal) : '—') + '</td>' +
          cols.map(function (c) {
            var v = r['系列'][c];
            return cell(v ? v['数量'] : 0, v ? v['金额'] : 0);
          }).join('') +
          cell(restQ, restM) +
          '<td class="num"><b>' + money(r['合计金额']) + '</b></td>' +
          '<td>' + (rate == null ? '<span class="cmp-na">无目标</span>' :
            '<div style="display:flex;align-items:center;gap:8px">' +
            '<div class="bar" style="flex:1"><i style="width:' +
            Math.min(rate * 100, 100).toFixed(1) + '%;background:' + col + '"></i></div>' +
            '<span style="font-size:12px;font-weight:700;color:' + col +
            ';min-width:48px;text-align:right">' + (rate * 100).toFixed(0) + '%</span>' +
            '</div>') + '</td>' +
        '</tr>';
      }).join('') +
      '<tr class="row-first"><td><b>合计</b></td><td></td>' +
        '<td class="num"><b>' + money(tk['标准']) + '</b></td>' +
        cols.map(function (c) {
          var q = 0, m = 0;
          pm.forEach(function (r) {
            var v = r['系列'][c];
            if (v) { q += v['数量']; m += v['金额']; }
          });
          return '<td class="num pm-cell" title="' + money(m) + ' 元"><b>' +
            (q % 1 === 0 ? q : q.toFixed(1)) + '</b> 台<span>' + moneyShort(m) + '</span></td>';
        }).join('') +
        (function () {
          var q = 0, m = 0;
          pm.forEach(function (r) {
            Object.keys(r['系列']).forEach(function (k) {
              if (cols.indexOf(k) < 0) { q += r['系列'][k]['数量']; m += r['系列'][k]['金额']; }
            });
          });
          return '<td class="num pm-cell" title="' + money(m) + ' 元"><b>' +
            (q % 1 === 0 ? q : q.toFixed(1)) + '</b> 台<span>' + moneyShort(m) + '</span></td>';
        })() +
        '<td class="num"><b>' + money(pm.reduce(function (a, x) { return a + x['合计金额']; }, 0)) +
        '</b></td><td></td></tr></tbody>';
  }

  /* ---------------- 合同明细 ---------------- */
  function renderDetail() {
    var d = state.data;
    var sel = $('filterStore');
    var opts = ['<option value="">全部门店</option>'].concat(
      d.stores.map(function (s) { return '<option value="' + esc(s.name) + '">' + esc(s.name) + '</option>'; })
    );
    sel.innerHTML = opts.join('');
    sel.value = state.filterStore;

    var q = state.q.trim().toLowerCase();
    var rows = d.records.filter(function (r) {
      if (state.filterStore && r.store !== state.filterStore) return false;
      if (state.filterPerson && r.person !== state.filterPerson) return false;
      if (!q) return true;
      return (r.no + ' ' + r.customer + ' ' + r.person + ' ' + r.store + ' ' + r.title).toLowerCase().indexOf(q) >= 0;
    });
    rows.sort(function (a, b) { return (b.date || '').localeCompare(a.date || ''); });

    var CAP = 400;
    var shown = rows.slice(0, CAP);
    var filterTxt = [];
    if (state.filterPerson) filterTxt.push('销售员=' + state.filterPerson + '（点表格标题旁的「清除」取消）');
    if (state.filterStore) filterTxt.push('门店=' + state.filterStore);
    if (q) filterTxt.push('搜索「' + state.q + '」');
    $('detailCount').innerHTML = '共 ' + int(rows.length) + ' 条' +
      (filterTxt.length ? '　·　筛选：' + esc(filterTxt.join('，')) : '') +
      (state.filterPerson ? '　<a href="#" id="clearPerson" style="color:#2e75b6">清除</a>' : '') +
      (rows.length > CAP ? '　·　只显示最近 ' + CAP + ' 条' : '');

    $('detailTable').innerHTML =
      '<thead><tr><th class="mid">签订日期</th><th>门店</th><th>销售员</th><th>合同编号</th>' +
      '<th>客户</th><th class="num">合同金额</th><th class="num">已回款</th><th>合同主题</th></tr></thead><tbody>' +
      (shown.length ? shown.map(function (r) {
        return '<tr>' +
          '<td class="mid">' + esc(r.date || '—') + '</td>' +
          '<td>' + esc(r.store) + '</td>' +
          '<td>' + esc(r.person) + '</td>' +
          '<td>' + esc(r.no) + '</td>' +
          '<td>' + esc(r.customer) + '</td>' +
          '<td class="num"><b>' + money(r.amount) + '</b></td>' +
          '<td class="num" style="color:var(--muted)">' + money(r.paid) + '</td>' +
          '<td style="color:var(--muted)">' + esc(r.title) + '</td>' +
        '</tr>';
      }).join('') : '<tr><td colspan="8" class="empty">没有匹配的合同</td></tr>') + '</tbody>';

    var clr = $('clearPerson');
    if (clr) clr.onclick = function (e) { e.preventDefault(); state.filterPerson = ''; renderDetail(); };
  }

  /* ---------------- 事件 ---------------- */
  function bind() {
    $('viewChips').addEventListener('click', function (e) {
      var b = e.target.closest('.chip'); if (!b) return;
      switchView(b.dataset.view);
    });

    // 「商场店 / 全部渠道」切换已去掉（三个店全是商场店），
    // 这里加个 if 兜底，免得以后又把这个块删了导致报错。
    var sc = $('scopeChips');
    if (sc) sc.addEventListener('click', function (e) {
      var b = e.target.closest('.chip'); if (!b) return;
      state.scope = b.dataset.scope;
      state.pdata = null;                // 范围变了，产品数据要重新取
      syncChips();
      load({ msg: '正在按「' + state.scope + '」重新统计…' });
    });

    $('rangeChips').addEventListener('click', function (e) {
      var b = e.target.closest('.chip'); if (!b) return;
      state.preset = b.dataset.preset;
      state.start = ''; state.end = ''; state.custom = false;
      state.pdata = null;
      syncChips();
      load({ msg: '正在取「' + state.preset + '」的数据…' });
    });

    $('btnQuery').addEventListener('click', function () {
      var f = $('dFrom').value, t = $('dTo').value;
      if (!f && !t) { toast('请先选日期，或点上面的时间快捷按钮'); return; }
      if (f && t && f > t) { toast('开始日期不能晚于结束日期'); return; }
      state.start = f; state.end = t; state.custom = true;
      state.pdata = null;
      syncChips();
      load({ msg: '正在取 ' + (f || '不限') + ' ~ ' + (t || '不限') + ' 的数据…' });
    });

    // ---- 产品视图的筛选 ----
    var pqt;
    $('pq').addEventListener('input', function () {
      var v = this.value;
      clearTimeout(pqt);
      pqt = setTimeout(function () { state.pq = v; renderPDetail(); }, 200);
    });
    $('pfilterCat').addEventListener('change', function () {
      state.pfilterCat = this.value; renderPDetail();
    });
    $('pfilterStore').addEventListener('change', function () {
      state.pfilterStore = this.value; renderPDetail();
    });

    $('btnRefresh').addEventListener('click', function () {
      state.force = true;
      load({ msg: '正在重新登录 ERP 抓取…', toast: '已重新抓取' });
    });

    $('btnReport').addEventListener('click', function () {
      var b = this;
      b.disabled = true; b.textContent = '生成中…';
      fetch('/api/report', { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (j.error) throw new Error(j.error);
          toast('报表已生成：' + j.file);
        })
        .catch(function (e) { toast('导出失败：' + e.message, true); })
        .then(function () { b.disabled = false; b.textContent = '导出 Excel'; });
    });

    var qt;
    $('q').addEventListener('input', function () {
      var v = this.value;
      clearTimeout(qt);
      qt = setTimeout(function () { state.q = v; renderDetail(); renderToday(); writeHash(); }, 200);
    });

    $('filterStore').addEventListener('change', function () {
      state.filterStore = this.value; renderDetail(); renderToday(); writeHash();
    });

    document.addEventListener('click', function (e) {
      var ps = e.target.closest('[data-pstore]');
      if (ps) {
        e.preventDefault();
        state.pfilterStore = ps.dataset.pstore;
        state.pfilterCat = '';
        $('pdetailTable').scrollIntoView({ behavior: 'smooth', block: 'center' });
        renderPDetail();
        toast('已筛选：' + state.pfilterStore);
        return;
      }
      var a = e.target.closest('.person-link, [data-person]');
      if (!a) return;
      e.preventDefault();
      state.filterPerson = a.dataset.person;
      state.filterStore = '';
      document.querySelector('#detailTable').scrollIntoView({ behavior: 'smooth', block: 'center' });
      renderDetail();
      toast('已筛选：' + state.filterPerson + ' 的合同明细');
    });
  }

  /* ---------------- 静态模式：没有后台，把需要服务的控件收起来 ---------------- */
  function enterStaticMode() {
    // 只清理自动刷新加的 ?v=1792...，保留 #筛选状态（和本地一致）。
    try { history.replaceState(null, '', location.pathname + location.hash); } catch (e) {}
    // 顶部区间按钮的高亮要跟着实际数据走 —— 静态页可能生成的是「本月」，
    // 不设这个就会出现"数据是本月、却亮着今年"的错位。
    if (STATIC.preset) state.preset = STATIC.preset;
    try { syncChips(); } catch (e) {}
    var when = esc(STATIC.fetchedAt || '');
    var span = esc((STATIC.range && STATIC.range.start) || '不限') + ' ~ ' +
               esc((STATIC.range && STATIC.range.end) || '不限');

    // 从地址推出「手动触发取数」的链接：
    //   用户名.github.io/仓库名  ->  github.com/用户名/仓库名/actions/workflows/refresh.yml
    var owner = (location.hostname.match(/^([^.]+)\.github\.io$/i) || [])[1] || '';
    var repo = (location.pathname.split('/')[1] || '');
    var actionsUrl = (owner && repo)
      ? 'https://github.com/' + owner + '/' + repo + '/actions/workflows/refresh.yml'
      : '';

    // 顶部说明条：只留一行状态（更新于 / 区间 / 范围）。
    // 那些"这不是实时数据""去 GitHub 点 Run workflow"之类的提示都去掉了 ——
    // 每天看的人不需要被反复提醒。
    var bar = document.createElement('div');
    bar.className = 'static-bar';
    bar.innerHTML =
      '<b>数据快照</b>　更新于 <span id="staticWhen">' + when + '</span>' +
      '<span class="static-age" id="staticAge"></span>' +
      '　·　区间 ' + span + '　·　范围 ' + esc(STATIC.scope || '');
    var wrap = document.querySelector('.wrap');
    if (wrap) wrap.insertBefore(bar, wrap.firstChild);

    // 数据"多旧"要一眼看出来 —— 每 30 秒更新一次这个标记
    function paintAge() {
      var el = $('staticAge');
      if (!el) return;
      var mins = null;
      try {
        var ft = new Date(String(STATIC.fetchedAt).replace(' ', 'T') + '+08:00');
        mins = Math.max(0, Math.round((Date.now() - ft) / 60000));
      } catch (e) {}
      if (mins === null) { el.textContent = ''; return; }
      var label = mins < 1 ? '刚刚' : (mins < 60 ? mins + ' 分钟前'
                  : (mins < 1440 ? Math.floor(mins / 60) + ' 小时前'
                                 : Math.floor(mins / 1440) + ' 天前'));
      el.textContent = '（' + label + '）';
      el.className = 'static-age' + (mins > 60 ? ' old' : (mins > 20 ? ' warm' : ''));
    }
    paintAge();
    setInterval(paintAge, 30000);

    // 「重新抓取」在静态页没法连 ERP，改成「检查更新」：
    // 去拉一次最新的部署，有新数据就刷新，没有就提示。
    var rf = $('btnRefresh');
    if (rf) {
      rf.disabled = false;
      rf.classList.remove('off');
      rf.textContent = '检查更新';
      rf.title = '去 GitHub 拉最新部署，有新数据就自动刷新';
      rf.addEventListener('click', function () { checkFresh(true); });
    }

    // 打开页面就先检查一次（有更新的部署就直接换上），之后每 2 分钟再查
    setTimeout(function () { checkFresh(false); }, 1500);
    var timer = setInterval(function () { checkFresh(false); }, 120000);
    window.addEventListener('beforeunload', function () { clearInterval(timer); });

    // 其余需要后台的功能仍然禁用
    ['btnQuery'].forEach(function (id) {
      var el = $(id);
      if (el) { el.disabled = true; el.classList.add('off'); el.title = '静态页面，没有后台服务'; }
    });
    ['scopeChips', 'rangeChips'].forEach(function (id) {
      var el = $(id);
      if (el) Array.prototype.forEach.call(el.querySelectorAll('.chip'), function (c) {
        c.classList.add('off');
      });
    });
    ['dFrom', 'dTo'].forEach(function (id) {
      var el = $(id);
      if (el) { el.disabled = true; el.classList.add('off'); }
    });
    var rep = $('btnReport');
    if (rep) { rep.disabled = true; rep.classList.add('off'); rep.title = '静态页面，没有后台服务'; }

    var b = document.querySelector('.brand small');
    if (b) b.textContent = '数据快照 · 定时更新';
  }

  // 静态页检查更新：拉一次同地址（带时间戳绕开缓存），比对 fetchedAt
  var _checking = false;
  function checkFresh(manual) {
    if (_checking) return;
    _checking = true;
    var url = location.pathname + '?v=' + Date.now();
    fetch(url, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (t) {
        _checking = false;
        if (!t) { if (manual) toast('检查失败，稍后再试', true); return; }
        var m = t.match(/window\.__DATA__=(\{[\s\S]*?\});/);
        if (!m) { if (manual) toast('页面格式变了，刷新一下就好'); return; }
        var nd;
        try { nd = JSON.parse(m[1]); } catch (e) { return; }
        if (nd.fetchedAt && nd.fetchedAt !== STATIC.fetchedAt) {
          // 有新数据 —— 直接换成新页面
          location.replace(location.pathname + '?v=' + Date.now());
        } else if (manual) {
          var mins = '';
          try {
            var ft = new Date(String(STATIC.fetchedAt).replace(' ', 'T') + '+08:00');
            mins = Math.max(0, Math.round((Date.now() - ft) / 60000)) + ' 分钟前';
          } catch (e) {}
          toast('已是最新（数据抓取于 ' + (STATIC.fetchedAt || '?') + (mins ? '，' + mins : '') + '）');
        }
      })
      .catch(function () { _checking = false; if (manual) toast('网络不通，稍后再试', true); });
  }

  /* ---------------- 启动 ---------------- */
  readHash();
  if (STATIC) enterStaticMode();
  syncChips();
  if (state.q) $('q').value = state.q;
  bind();
  load();
  if (state.view === 'product') switchView('product');

  window.addEventListener('hashchange', function () {
    var before = state.scope + '|' + state.preset + '|' + state.start + '|' + state.end;
    readHash();
    var after = state.scope + '|' + state.preset + '|' + state.start + '|' + state.end;
    syncChips();
    if (before !== after) load();
  });
})();
