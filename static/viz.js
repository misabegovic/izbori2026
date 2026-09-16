/* Analitika: sve slike crta D3 iz podataka u data-d3 atributu. Bez JS ostaje tekst. */
(function () {
  var COL = { 'c-blue': '#2a78d6', 'c-blue2': '#86b6ef', 'c-za': '#0ca30c', 'c-protiv': '#d03b3b', 'c-uz': '#fab219', 'c-od': '#a9a9a9', 'c-new': '#c3c2b7', 'c-sw': '#eb6834' };
  var MUT = '#5c5c5c', INK = '#181818', LINE = '#dedbd3';
  // 1421 -> '1.421', the separator used everywhere else on the site
  function fmt(v) { return (v == null ? '' : v.toLocaleString('de-DE')); }
  function tipFor(host) {
    var tip = document.createElement('div'); tip.className = 'viz-tip'; tip.style.display = 'none'; host.style.position = 'relative'; host.appendChild(tip);
    return function (html, ev) {
      if (!html) { tip.style.display = 'none'; return; }
      tip.innerHTML = html; tip.style.display = 'block';
      var r = host.getBoundingClientRect(); var W = host.clientWidth || 300;
      tip.style.left = Math.max(0, Math.min(W - 240, ev.clientX - r.left - 120)) + 'px'; tip.style.top = (ev.clientY - r.top + 14) + 'px';
      setTimeout(function () { document.addEventListener('click', function h(e) { if (!tip.contains(e.target)) { tip.style.display = 'none'; document.removeEventListener('click', h); } }); }, 0);
    };
  }
  function bar(el, d) {
    el.innerHTML = '';
    var W = el.clientWidth || 300, h = 30, lab = d.label ? 16 : 0;
    var svg = d3.select(el).append('svg').attr('width', W).attr('height', h + lab);
    if (d.label) svg.append('text').attr('x', 0).attr('y', 12).attr('font-size', '.68rem').attr('fill', INK).text(d.label);
    var vw = 70, x = d3.scaleLinear().domain([0, d.max || 1]).range([0, W - vw]);
    svg.append('rect').attr('x', 0).attr('y', lab + 8).attr('width', W - vw).attr('height', 14).attr('rx', 4).attr('fill', '#eceae3');
    svg.append('rect').attr('x', 0).attr('y', lab + 8).attr('height', 14).attr('rx', 4).attr('fill', COL[d.cls] || COL['c-blue']).attr('width', 0)
      .transition().duration(600).attr('width', Math.max(2, x(d.v)));
    svg.append('text').attr('x', W).attr('y', lab + 20).attr('text-anchor', 'end').attr('font-size', '.63rem').attr('fill', MUT).text(d.text);
  }
  function stack(el, d) {
    el.innerHTML = '';
    var parts = d.parts.filter(function (p) { return p[1]; }); var tot = d3.sum(parts, function (p) { return p[1]; }) || 1;
    var W = el.clientWidth || 300, h = 16;
    var svg = d3.select(el).append('svg').attr('width', W).attr('height', h);
    var show = tipFor(el);
    var x = 0;
    parts.forEach(function (p, i) {
      var w = Math.max(3, (W - 2 * (parts.length - 1)) * p[1] / tot);
      svg.append('rect').attr('x', x).attr('y', 0).attr('width', w).attr('height', h).attr('rx', 3).attr('fill', COL[p[2]] || '#999')
        .style('cursor', 'pointer').on('click', function (ev) { ev.stopPropagation(); show('<b>' + p[0] + '</b>: ' + p[1] + (d.total ? ' od ' + d.total + ' (' + Math.round(100 * p[1] / d.total) + '%)' : ''), ev); });
      x += w + 2;
    });
    var leg = document.createElement('div'); leg.className = 'st-l';
    parts.forEach(function (p) { var s = document.createElement('span'); s.innerHTML = '<i class="sw" style="background:' + (COL[p[2]] || '#999') + '"></i>' + p[0] + ' ' + p[1] + (d.total ? ' (' + Math.round(100 * p[1] / d.total) + '%)' : ''); leg.appendChild(s); });
    el.appendChild(leg);
  }
  function chance(el, d) {
    el.innerHTML = '';
    var sm = el.classList.contains('sm'), R = sm ? 22 : 34, W = el.clientWidth || 300;
    var col = d.pct >= 50 ? COL['c-za'] : d.pct >= 15 ? COL['c-uz'] : '#a9a9a9';
    var svg = d3.select(el).append('svg').attr('width', W).attr('height', 2 * R + 4);
    var g = svg.append('g').attr('transform', 'translate(' + (R + 2) + ',' + (R + 2) + ')');
    var arc = d3.arc().innerRadius(R - 7).outerRadius(R).startAngle(0);
    g.append('path').attr('d', arc({ endAngle: 2 * Math.PI })).attr('fill', '#eceae3');
    g.append('path').attr('fill', col).transition().duration(700).attrTween('d', function () { var i = d3.interpolate(0, 2 * Math.PI * d.pct / 100); return function (t) { return arc({ endAngle: i(t) }); }; });
    g.append('text').attr('text-anchor', 'middle').attr('dy', 5).attr('font-size', sm ? '.58rem' : '.74rem').attr('font-weight', 700).attr('fill', INK).text('~' + d.pct + '%');
    svg.append('text').attr('x', 2 * R + 12).attr('y', R - 4).attr('font-size', sm ? '.68rem' : '.79rem').attr('font-weight', 700).attr('fill', INK).text('Šansa za mjesto: ' + d.word);
    svg.append('text').attr('x', 2 * R + 12).attr('y', R + 14).attr('font-size', '.7rem').attr('fill', MUT).text('iz rezultata 2022, nije prognoza');
    var why = document.createElement('div'); why.className = 'small mut'; why.textContent = 'Zašto: ' + d.why + '.'; el.appendChild(why);
  }
  function years(el, d) {
    el.innerHTML = '';
    var W = el.clientWidth || 300, n = d.length + 1, step = Math.min(56, (W - 30) / n), h = 44;
    var svg = d3.select(el).append('svg').attr('width', W).attr('height', h);
    var show = tipFor(el);
    svg.append('line').attr('x1', 14).attr('x2', 14 + step * (n - 1)).attr('y1', 16).attr('y2', 16).attr('stroke', LINE).attr('stroke-width', 2);
    d.concat([{ y: 2026, now: true }]).forEach(function (t, i) {
      var x = 14 + step * i;
      svg.append('circle').attr('cx', x).attr('cy', 16).attr('r', 0).attr('fill', t.now ? '#fff' : (t.won ? COL['c-blue'] : '#fff')).attr('stroke', t.now ? COL['c-sw'] : COL['c-blue']).attr('stroke-width', 2.5).attr('stroke-dasharray', t.now ? '3 2' : null)
        .style('cursor', 'pointer').on('click', function (ev) { ev.stopPropagation(); show('<b>' + t.y + '</b><br>' + (t.now ? 'sada na listiću' : (t.lvl || '') + '<br>' + (t.won ? '<b>izabran/a</b>' : 'nije izabran/a')), ev); })
        .transition().delay(i * 60).attr('r', 8);
      svg.append('text').attr('x', x).attr('y', 38).attr('text-anchor', 'middle').attr('font-size', '.58rem').attr('fill', MUT).text(t.y);
    });
    var leg = document.createElement('div'); leg.className = 'st-l';
    leg.innerHTML = '<span><i class="sw" style="background:' + COL['c-blue'] + '"></i>izabran/a</span><span><i class="sw" style="background:#fff;border:2px solid ' + COL['c-blue'] + '"></i>nije izabran/a</span><span><i class="sw" style="background:#fff;border:2px dashed ' + COL['c-sw'] + '"></i>sada</span>';
    el.appendChild(leg);
  }
  function mandates(el, d) {
    el.innerHTML = '';
    var W = el.clientWidth || 300, rowH = 44, top = 6, labW = 82;
    var svg = d3.select(el).append('svg').attr('width', W).attr('height', top + d.length * rowH + 4);
    var show = tipFor(el);
    d.forEach(function (r, i) {
      var y = top + i * rowH, t = r.t || 0, x0 = labW, w = W - labW - 44;
      svg.append('text').attr('x', 0).attr('y', y + 18).attr('font-size', '.68rem').attr('font-weight', 700).attr('fill', INK).text(r.m);
      svg.append('rect').attr('x', x0).attr('y', y + 6).attr('width', w).attr('height', 16).attr('rx', 4).attr('fill', '#eceae3');
      if (t) {
        var x = x0;
        [['ispunjeno', r.f, COL['c-za']], ['djelimično', r.p, COL['c-uz']], ['nije', r.b, COL['c-protiv']]].forEach(function (s) {
          if (!s[1]) return; var ww = w * s[1] / t;
          svg.append('rect').attr('x', x).attr('y', y + 6).attr('width', 0).attr('height', 16).attr('fill', s[2]).style('cursor', 'pointer')
            .on('click', function (ev) { ev.stopPropagation(); show('<b>' + r.m + '</b><br>' + s[0] + ': ' + s[1] + ' od ' + t + ' (' + Math.round(100 * s[1] / t) + '%)<br><span class="small mut">' + r.power + '</span>', ev); })
            .transition().duration(600).attr('width', Math.max(2, ww - 1));
          x += ww;
        });
        svg.append('text').attr('x', W).attr('y', y + 19).attr('text-anchor', 'end').attr('font-size', '.63rem').attr('fill', MUT).text(Math.round(100 * r.f / t) + '%');
      } else {
        svg.append('text').attr('x', x0 + 6).attr('y', y + 18).attr('font-size', '.63rem').attr('fill', MUT).text('nema brojki po stranci za ovaj mandat');
      }
      var pw = svg.append('text').attr('x', x0).attr('y', y + 36).attr('font-size', '.55rem').attr('fill', MUT).text(r.power);
      var n = pw.node(); while (n.getComputedTextLength() > w + 40 && n.textContent.length > 8) n.textContent = n.textContent.slice(0, -4) + '…';
    });
    var leg = document.createElement('div'); leg.className = 'st-l';
    leg.innerHTML = '<span><i class="sw" style="background:' + COL['c-za'] + '"></i>ispunjeno</span><span><i class="sw" style="background:' + COL['c-uz'] + '"></i>djelimično</span><span><i class="sw" style="background:' + COL['c-protiv'] + '"></i>nije</span><span><i class="sw" style="background:#eceae3"></i>bez ocjene</span><span>% = ispunjeno u potpunosti</span>';
    el.appendChild(leg);
  }
  var METRICS = [
    { k: 'ch', label: 'šansa za mjesto', fmt: function (v) { return '~' + v + '%'; }, only: true },
    { k: 'w', label: 'koliko puta biran', fmt: function (v) { return v + '×'; } },
    { k: 's', label: 'koliko puta na listi', fmt: function (v) { return v + '×'; } },
    { k: 'p', label: 'promjene stranaka', fmt: function (v) { return v + (v == 1 ? ' stranka' : ' stranke'); } },
    { k: 'v22', label: 'lični glasovi 2022', fmt: function (v) { return v.toLocaleString('de-DE'); }, only: true },
    { k: 'za', label: '% glasao „za” (poslanici)', fmt: function (v) { return v + '%'; }, only: true },
    { k: 'pris', label: '% prisutan (poslanici)', fmt: function (v) { return v + '%'; }, only: true }
  ];
  function swarm(el) {
    var data = JSON.parse(document.getElementById(el.dataset.src).textContent);
    var lists = data.lists, cands = data.cands, me = el.dataset.me || null;
    var W = el.clientWidth || 360, left = 8, right = 26, top = 26;
    var bar = document.createElement('div'); bar.className = 'viz-bar'; el.appendChild(bar);
    var show = tipFor(el);
    var svg = d3.select(el).append('svg').attr('width', W);
    var cur = METRICS[1];
    METRICS.forEach(function (m) {
      var b = document.createElement('button'); b.textContent = m.label; b.className = 'tog';
      b.onclick = function () { cur = m; draw(); bar.querySelectorAll('button').forEach(function (x) { x.classList.remove('on'); }); b.classList.add('on'); };
      if (m === cur) b.classList.add('on');
      bar.appendChild(b);
    });
    function draw() {
      svg.selectAll('*').remove(); show(null);
      var pts = cands.filter(function (c) { return c[cur.k] != null; });
      var byList = {}; pts.forEach(function (c) { byList[c.l] = 1; });
      var rows = lists.map(function (n, i) { return { i: i, n: n }; }).filter(function (r) { return byList[r.i] || !cur.only; });
      var bucket = {}; pts.forEach(function (c) { var k = c.l + ':' + c[cur.k]; bucket[k] = (bucket[k] || 0) + 1; });
      var maxB = d3.max(Object.keys(bucket), function (k) { return bucket[k]; }) || 1;
      var rad = maxB > 20 ? 4.5 : 5.5;
      var rowH = Math.max(34, Math.min(110, Math.round(2.2 * rad * Math.sqrt(maxB) + 14)));
      var H = top + rows.length * rowH + 10;
      svg.attr('height', H);
      var cnt = el.querySelector('.viz-cnt'); if (!cnt) { cnt = document.createElement('div'); cnt.className = 'small mut viz-cnt'; el.insertBefore(cnt, svg.node()); } cnt.textContent = pts.length < cands.length ? 'Prikazano ' + pts.length + ' od ' + cands.length + ' ljudi (ostali nemaju ovaj podatak).' : 'Svih ' + cands.length + ' ljudi.';
      var max = d3.max(pts, function (c) { return c[cur.k]; }) || 1;
      var labelW = Math.round(W * 0.42);
      var x = d3.scaleLinear().domain([0, cur.k === 'ch' ? 100 : max]).range([left + labelW, W - right]).nice();
      var yOf = {}; rows.forEach(function (r, j) { yOf[r.i] = top + j * rowH + rowH / 2; });
      var g = svg.append('g');
      g.append('g').attr('transform', 'translate(0,' + (top - 8) + ')').call(d3.axisTop(x).ticks(4).tickFormat(function (v) { return cur.fmt(v); })).attr('class', 'viz-axis');
      rows.forEach(function (r, j) {
        var y = top + j * rowH + rowH / 2;
        g.append('line').attr('x1', left + labelW).attr('x2', W - right).attr('y1', y).attr('y2', y).attr('class', 'viz-grid');
        var t = g.append('text').attr('x', left).attr('y', y + 4).attr('class', 'viz-lab').text((r.i + 1) + '. ' + r.n);
        var tn = t.node(); while (tn.getComputedTextLength() > labelW - 8 && tn.textContent.length > 4) tn.textContent = tn.textContent.slice(0, -2) + '…';
      });
      var sim = d3.forceSimulation(pts).force('x', d3.forceX(function (c) { return x(c[cur.k]); }).strength(1)).force('y', d3.forceY(function (c) { return yOf[c.l]; }).strength(0.4)).force('c', d3.forceCollide(rad + 1)).stop();
      for (var i = 0; i < 90; i++) sim.tick();
      pts.forEach(function (c) { c.y = Math.max(yOf[c.l] - rowH / 2 + rad, Math.min(yOf[c.l] + rowH / 2 - rad, c.y)); c.x = Math.max(left + labelW + rad, Math.min(W - right, c.x)); });
      g.selectAll('circle').data(pts).enter().append('circle')
        .attr('cx', function (c) { return c.x; }).attr('cy', function (c) { return c.y; }).attr('r', 0)
        .attr('class', function (c) { return 'viz-dot' + (c.rec ? ' rec' : '') + (c.id === me ? ' me' : ''); })
        .on('click', function (ev, c) { ev.stopPropagation(); show((c.img ? '<img class="av" src="' + c.img + '" alt=""> ' : '') + '<b>' + c.n + '</b><br><span class="mut small">' + lists[c.l] + ', ' + c.pos + '. na listi</span><br>' + cur.label + ': <b>' + cur.fmt(c[cur.k]) + '</b>' + (c.chw ? '<br>šansa za mjesto: ' + c.chw : '') + (c.story ? '<br><span class="small">' + c.story + '</span>' : '') + (c.href ? '<br><a href="' + c.href + '">cijela priča →</a>' : ''), ev); })
        .transition().duration(400).attr('r', function (c) { return c.id === me ? 9 : rad; });
      if (me) { var m = pts.filter(function (c) { return c.id === me; })[0]; if (m) { var tx = Math.max(left + labelW + 40, Math.min(W - right - 40, m.x)); g.append('text').attr('x', tx).attr('y', m.y - 13).attr('text-anchor', 'middle').attr('class', 'viz-me').text('ovaj kandidat'); } }
    }
    draw();
  }
  function vbars(el, d) {
    // d: {rows:[{y, pct, voted, total}], avg} — one bar per year, attendance over time
    el.innerHTML = '';
    var W = el.clientWidth || 300, H = 92, top = 18, bot = 20, n = d.rows.length, bw = Math.min(64, (W - 10) / n - 8);
    var svg = d3.select(el).append('svg').attr('width', W).attr('height', H);
    var show = tipFor(el);
    var x = function (i) { return 6 + i * ((W - 12) / n) + ((W - 12) / n - bw) / 2; };
    var y = d3.scaleLinear().domain([0, 100]).range([H - bot, top]);
    if (d.avg != null) svg.append('line').attr('x1', 0).attr('x2', W).attr('y1', y(d.avg)).attr('y2', y(d.avg)).attr('stroke', MUT).attr('stroke-dasharray', '3 3');
    d.rows.forEach(function (r, i) {
      var col = r.pct >= 80 ? COL['c-za'] : r.pct >= 60 ? COL['c-uz'] : COL['c-protiv'];
      svg.append('rect').attr('x', x(i)).attr('y', y(0)).attr('width', bw).attr('height', 0).attr('rx', 4).attr('fill', col).style('cursor', 'pointer')
        .on('click', function (ev) { ev.stopPropagation(); show('<b>' + r.y + '</b>: glasao/la na ' + r.voted + ' od ' + r.total + ' glasanja (' + r.pct + '%)', ev); })
        .transition().duration(600).attr('y', y(r.pct)).attr('height', y(0) - y(r.pct));
      svg.append('text').attr('x', x(i) + bw / 2).attr('y', y(r.pct) - 4).attr('text-anchor', 'middle').attr('font-size', '.68rem').attr('font-weight', 700).attr('fill', INK).text(r.pct + '%');
      svg.append('text').attr('x', x(i) + bw / 2).attr('y', H - 5).attr('text-anchor', 'middle').attr('font-size', '.68rem').attr('fill', MUT).text(r.y);
    });
    if (d.avg != null) { var leg = document.createElement('div'); leg.className = 'st-l'; leg.innerHTML = '<span>- - - prosjek svih poslanika za cijeli mandat: ' + d.avg + '%</span>'; el.appendChild(leg); }
  }
  function votes(el, d) {
    // d: {rows:[{y, votes, label, rank, of, pct, elected}]} — personal votes per election.
    // Height is the vote count, not a percentage, because the question this answers is
    // "how many people wrote this name down", and the rank underneath says how that
    // compared with everyone the person shared a list with.
    el.innerHTML = '';
    var W = el.clientWidth || 300, H = 118, top = 22, bot = 34, n = d.rows.length;
    if (!n) return;
    var bw = Math.min(64, (W - 10) / n - 8);
    var svg = d3.select(el).append('svg').attr('width', W).attr('height', H);
    var show = tipFor(el);
    var max = d3.max(d.rows, function (r) { return r.votes; }) || 1;
    var x = function (i) { return 6 + i * ((W - 12) / n) + ((W - 12) / n - bw) / 2; };
    var y = d3.scaleLinear().domain([0, max]).range([H - bot, top]);
    d.rows.forEach(function (r, i) {
      var col = r.elected ? COL['c-za'] : COL['c-blue'];
      svg.append('rect').attr('x', x(i)).attr('y', y(0)).attr('width', bw).attr('height', 0).attr('rx', 4)
        .attr('fill', col).style('cursor', 'pointer')
        .on('click', function (ev) {
          ev.stopPropagation();
          var s = '<b>' + r.y + '</b> ' + r.label + '<br>' + fmt(r.votes) + ' glasova';
          if (r.rank) s += '<br>' + r.rank + '. od ' + r.of + ' ljudi na svojoj listi';
          if (r.pct) s += ' (' + Math.round(r.pct) + '% svih glasova liste)';
          s += '<br>' + (r.elected ? 'izabran/a' : 'nije izabran/a');
          show(s, ev);
        })
        .transition().duration(600).attr('y', y(r.votes)).attr('height', y(0) - y(r.votes));
      svg.append('text').attr('x', x(i) + bw / 2).attr('y', y(r.votes) - 5).attr('text-anchor', 'middle')
        .attr('font-size', '.68rem').attr('font-weight', 700).attr('fill', INK).text(fmt(r.votes));
      svg.append('text').attr('x', x(i) + bw / 2).attr('y', H - 18).attr('text-anchor', 'middle')
        .attr('font-size', '.68rem').attr('fill', MUT).text(r.y);
      if (r.rank) svg.append('text').attr('x', x(i) + bw / 2).attr('y', H - 5).attr('text-anchor', 'middle')
        .attr('font-size', '.62rem').attr('fill', r.rank === 1 ? COL['c-za'] : MUT)
        .attr('font-weight', r.rank === 1 ? 700 : 400).text(r.rank + '/' + r.of);
    });
    var leg = document.createElement('div');
    leg.className = 'st-l';
    leg.innerHTML = '<span>Stub je broj glasova. Ispod godine piše koje je bio po glasovima na svojoj listi.</span>';
    el.appendChild(leg);
  }
  function heat(el, d) {
    // d: {parties:[], mps:[], m:[[pct|null]]} — party x party agreement
    el.innerHTML = '';
    var n = d.parties.length, W = el.clientWidth || 300, lab = Math.min(96, Math.max(66, W * 0.26)), cell = Math.min(46, Math.floor((W - lab - 4) / n)), H = lab * 0.8 + n * cell + 6;
    var cut = function (s) { return s.length > 12 ? s.slice(0, 11) + '…' : s; };
    var svg = d3.select(el).append('svg').attr('width', W).attr('height', H);
    var show = tipFor(el);
    var col = d3.scaleLinear().domain([30, 65, 100]).range(['#d03b3b', '#fab219', '#0ca30c']).clamp(true);
    var ty = lab * 0.8;
    d.parties.forEach(function (p, j) {
      svg.append('text').attr('transform', 'translate(' + (lab + j * cell + cell / 2 + 4) + ',' + (ty - 6) + ') rotate(-55)').attr('font-size', '.68rem').attr('fill', INK).text(cut(p));
    });
    d.parties.forEach(function (p, i) {
      svg.append('text').attr('x', 0).attr('y', ty + i * cell + cell / 2 + 4).attr('font-size', '.7rem').attr('fill', INK).text(cut(p));
      d.parties.forEach(function (q, j) {
        var v = d.m[i][j];
        var g = svg.append('g').style('cursor', 'pointer').on('click', function (ev) { ev.stopPropagation(); show('<b>' + p + '</b> i <b>' + q + '</b>' + (v == null ? '<br>premalo zajedničkih glasanja' : '<br>glasali isto u <b>' + v + '%</b> glasanja (' + d.n[i][j] + ' zajedničkih)'), ev); });
        g.append('rect').attr('x', lab + j * cell + 1).attr('y', ty + i * cell + 1).attr('width', cell - 2).attr('height', cell - 2).attr('rx', 4).attr('fill', v == null ? '#f0efe9' : (i === j ? '#e6e4dc' : col(v)));
        if (v != null && i !== j) g.append('text').attr('x', lab + j * cell + cell / 2).attr('y', ty + i * cell + cell / 2 + 4).attr('text-anchor', 'middle').attr('font-size', cell < 34 ? '.55rem' : '.66rem').attr('font-weight', 700).attr('fill', v >= 45 && v < 80 ? INK : '#fff').text(v);
      });
    });
    var leg = document.createElement('div'); leg.className = 'st-l';
    leg.innerHTML = '<span><i class="sw" style="background:#0ca30c"></i>skoro uvijek isto</span><span><i class="sw" style="background:#fab219"></i>pola-pola</span><span><i class="sw" style="background:#d03b3b"></i>uglavnom suprotno</span>';
    el.appendChild(leg);
  }
  function init() {
    document.querySelectorAll('.d3-vbars').forEach(function (el) { vbars(el, JSON.parse(el.dataset.d3)); });
    document.querySelectorAll('.d3-votes').forEach(function (el) { votes(el, JSON.parse(el.dataset.d3)); });
    document.querySelectorAll('.d3-heat').forEach(function (el) { heat(el, JSON.parse(el.dataset.d3)); });
    document.querySelectorAll('.d3-bar').forEach(function (el) { bar(el, JSON.parse(el.dataset.d3)); });
    document.querySelectorAll('.d3-stack').forEach(function (el) { stack(el, JSON.parse(el.dataset.d3)); });
    document.querySelectorAll('.d3-chance').forEach(function (el) { chance(el, JSON.parse(el.dataset.d3)); });
    document.querySelectorAll('.d3-mandates').forEach(function (el) { mandates(el, JSON.parse(el.dataset.d3)); });
    document.querySelectorAll('.d3-years').forEach(function (el) { years(el, JSON.parse(el.dataset.d3)); });
    document.querySelectorAll('.viz').forEach(swarm);
    if (window.cyrRefresh) window.cyrRefresh();
  }
  if (window.d3) init(); else { var s = document.createElement('script'); s.src = 'https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js'; s.onload = init; document.head.appendChild(s); }
})();
