/* Uporedi kandidate: D3 beeswarm, jedan krug = jedan kandidat, red = lista. */
(function () {
  var METRICS = [
    { k: 'w', label: 'koliko puta biran', fmt: function (v) { return v + '×'; } },
    { k: 's', label: 'koliko puta na listi', fmt: function (v) { return v + '×'; } },
    { k: 'p', label: 'promjene stranaka', fmt: function (v) { return v + ' stranke'; } },
    { k: 'v22', label: 'lični glasovi 2022', fmt: function (v) { return v.toLocaleString('de-DE'); }, only: true },
    { k: 'za', label: '% glasao „za” (poslanici)', fmt: function (v) { return v + '%'; }, only: true },
    { k: 'pris', label: '% prisutan (poslanici)', fmt: function (v) { return v + '%'; }, only: true }
  ];
  function build(el) {
    var data = JSON.parse(document.getElementById(el.dataset.src).textContent);
    var lists = data.lists, cands = data.cands, me = el.dataset.me || null;
    var W = el.clientWidth || 360, left = 8, right = 26, top = 26;
    var bar = document.createElement('div'); bar.className = 'viz-bar'; el.appendChild(bar);
    var tip = document.createElement('div'); tip.className = 'viz-tip'; tip.style.display = 'none'; el.appendChild(tip);
    var svg = d3.select(el).append('svg').attr('width', W);
    var cur = METRICS[0];
    METRICS.forEach(function (m) {
      var b = document.createElement('button'); b.textContent = m.label; b.className = 'tog';
      b.onclick = function () { cur = m; draw(); bar.querySelectorAll('button').forEach(function (x) { x.classList.remove('on'); }); b.classList.add('on'); };
      if (m === cur) b.classList.add('on');
      bar.appendChild(b);
    });
    function draw() {
      svg.selectAll('*').remove(); tip.style.display = 'none';
      var pts = cands.filter(function (c) { return c[cur.k] != null; });
      var byList = {}; pts.forEach(function (c) { byList[c.l] = 1; });
      var rows = lists.map(function (n, i) { return { i: i, n: n }; }).filter(function (r) { return byList[r.i] || !cur.only; });
      var bucket = {}; pts.forEach(function (c) { var k = c.l + ':' + c[cur.k]; bucket[k] = (bucket[k] || 0) + 1; });
      var maxB = d3.max(Object.keys(bucket), function (k) { return bucket[k]; }) || 1;
      var rad = maxB > 20 ? 4.5 : 5.5;
      var rowH = Math.max(34, Math.min(110, Math.round(2.2 * rad * Math.sqrt(maxB) + 14)));
      var H = top + rows.length * rowH + 10;
      svg.attr('height', H);
      var max = d3.max(pts, function (c) { return c[cur.k]; }) || 1;
      var labelW = Math.round(W * 0.42);
      var x = d3.scaleLinear().domain([0, max]).range([left + labelW, W - right]).nice();
      var yOf = {}; rows.forEach(function (r, j) { yOf[r.i] = top + j * rowH + rowH / 2; });
      var rowHs = rowH;
      var g = svg.append('g');
      g.append('g').attr('transform', 'translate(0,' + (top - 8) + ')').call(d3.axisTop(x).ticks(4).tickFormat(function (v) { return cur.fmt(v); }))
        .attr('class', 'viz-axis');
      rows.forEach(function (r, j) {
        var y = top + j * rowH + rowH / 2;
        g.append('line').attr('x1', left + labelW).attr('x2', W - right).attr('y1', y).attr('y2', y).attr('class', 'viz-grid');
        var t = g.append('text').attr('x', left).attr('y', y + 4).attr('class', 'viz-lab').text((r.i + 1) + '. ' + r.n);
        var tn = t.node(); while (tn.getComputedTextLength() > labelW - 8 && tn.textContent.length > 4) tn.textContent = tn.textContent.slice(0, -2) + '…';
      });
      var sim = d3.forceSimulation(pts)
        .force('x', d3.forceX(function (c) { return x(c[cur.k]); }).strength(1))
        .force('y', d3.forceY(function (c) { return yOf[c.l]; }).strength(0.4))
        .force('c', d3.forceCollide(rad + 1)).stop();
      for (var i = 0; i < 90; i++) sim.tick();
      pts.forEach(function (c) { c.y = Math.max(yOf[c.l] - rowH / 2 + rad, Math.min(yOf[c.l] + rowH / 2 - rad, c.y)); c.x = Math.max(left + labelW + rad, Math.min(W - right, c.x)); });
      var dots = g.selectAll('circle').data(pts).enter().append('circle')
        .attr('cx', function (c) { return c.x; }).attr('cy', function (c) { return c.y; })
        .attr('r', function (c) { return c.id === me ? 9 : rad; })
        .attr('class', function (c) { return 'viz-dot' + (c.rec ? ' rec' : '') + (c.id === me ? ' me' : ''); })
        .on('click', function (ev, c) { show(c, ev); }).on('mouseenter', function (ev, c) { show(c, ev); });
      if (me) { var m = pts.filter(function (c) { return c.id === me; })[0]; if (m) { var tx = Math.max(left + labelW + 40, Math.min(W - right - 40, m.x)); g.append('text').attr('x', tx).attr('y', m.y - 13).attr('text-anchor', 'middle').attr('class', 'viz-me').text('ovaj kandidat'); } }
      function show(c, ev) {
        tip.innerHTML = '<b>' + c.n + '</b><br><span class="mut small">' + lists[c.l] + ', ' + c.pos + '. na listi</span><br>' + cur.label + ': <b>' + cur.fmt(c[cur.k]) + '</b>' + (c.story ? '<br><span class="small">' + c.story + '</span>' : '') + (c.href ? '<br><a href="' + c.href + '">cijela priča →</a>' : '');
        tip.style.display = 'block';
        var r = el.getBoundingClientRect(); var px = ev.clientX - r.left, py = ev.clientY - r.top;
        tip.style.left = Math.max(0, Math.min(W - 240, px - 120)) + 'px'; tip.style.top = (py + 14) + 'px';
      }
      el.addEventListener('click', function (ev) { if (ev.target.tagName !== 'circle' && !tip.contains(ev.target)) tip.style.display = 'none'; });
    }
    draw();
  }
  function init() { document.querySelectorAll('.viz').forEach(build); }
  if (window.d3) init(); else { var s = document.createElement('script'); s.src = 'https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js'; s.onload = init; document.head.appendChild(s); }
})();
