(function () {
    var MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'];
    var WEEKDAYS = ['ش', 'ی', 'د', 'س', 'چ', 'پ', 'ج'];

    function div(a, b) { return ~~(a / b); }
    function mod(a, b) { return a - ~~(a / b) * b; }

    function jalCal(jy) {
        var breaks = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178];
        var gy = jy + 621, leapJ = -14, jp = breaks[0], jump = 0, n, i, jm;
        for (i = 1; i < breaks.length; i++) {
            jm = breaks[i];
            jump = jm - jp;
            if (jy < jm) break;
            leapJ += div(jump, 33) * 8 + div(mod(jump, 33), 4);
            jp = jm;
        }
        n = jy - jp;
        leapJ += div(n, 33) * 8 + div(mod(n, 33) + 3, 4);
        if (mod(jump, 33) === 4 && jump - n === 4) leapJ += 1;
        var leapG = div(gy, 4) - div((div(gy, 100) + 1) * 3, 4) - 150;
        var march = 20 + leapJ - leapG;
        if (jump - n < 6) n = n - jump + div(jump + 4, 33) * 33;
        var leap = mod(mod(n + 1, 33) - 1, 4);
        if (leap === -1) leap = 4;
        return { leap: leap, gy: gy, march: march };
    }

    function g2d(gy, gm, gd) {
        var d = div((gy + div(gm - 8, 6) + 100100) * 1461, 4) + div(153 * mod(gm + 9, 12) + 2, 5) + gd - 34840408;
        return d - div(div(gy + 100100 + div(gm - 8, 6), 100) * 3, 4) + 752;
    }

    function d2g(jdn) {
        var j = 4 * jdn + 139361631;
        j = j + div(div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908;
        var i = div(mod(j, 1461), 4) * 5 + 308;
        var gd = div(mod(i, 153), 5) + 1;
        var gm = mod(div(i, 153), 12) + 1;
        var gy = div(j, 1461) - 100100 + div(8 - gm, 6);
        return [gy, gm, gd];
    }

    function j2d(jy, jm, jd) {
        var r = jalCal(jy);
        return g2d(r.gy, 3, r.march) + (jm - 1) * 31 - div(jm, 7) * (jm - 7) + jd - 1;
    }

    function d2j(jdn) {
        var gy = d2g(jdn)[0], jy = gy - 621, r = jalCal(jy), jdn1f = g2d(gy, 3, r.march), jd, jm, k;
        k = jdn - jdn1f;
        if (k >= 0) {
            if (k <= 185) {
                jm = 1 + div(k, 31);
                jd = mod(k, 31) + 1;
                return [jy, jm, jd];
            }
            k -= 186;
        } else {
            jy -= 1;
            k += 179;
            if (r.leap === 1) k += 1;
        }
        jm = 7 + div(k, 30);
        jd = mod(k, 30) + 1;
        return [jy, jm, jd];
    }

    function daysInMonth(jy, jm) {
        if (jm <= 6) return 31;
        if (jm <= 11) return 30;
        return jalCal(jy).leap === 0 ? 30 : 29;
    }

    function pad(n) { return (n < 10 ? '0' : '') + n; }
    function fmt(y, m, d) { return y + '/' + pad(m) + '/' + pad(d); }

    function parse(value) {
        var m = (value || '').trim().match(/^(\d{4})\/(\d{1,2})\/(\d{1,2})$/);
        return m ? { y: +m[1], m: +m[2], d: +m[3] } : null;
    }

    function todayJalali() {
        var now = new Date();
        var t = d2j(g2d(now.getFullYear(), now.getMonth() + 1, now.getDate()));
        return { y: t[0], m: t[1], d: t[2] };
    }

    var popup = null;
    var state = { input: null, y: 0, m: 0, sel: null };

    function buildPopup() {
        popup = document.createElement('div');
        popup.className = 'jdp-popup';
        popup.hidden = true;
        popup.innerHTML =
            '<div class="jdp-nav">' +
            '<button type="button" class="jdp-nav-btn" data-nav="prev">›</button>' +
            '<span class="jdp-label"></span>' +
            '<button type="button" class="jdp-nav-btn" data-nav="next">‹</button>' +
            '</div>' +
            '<div class="jdp-weekdays">' + WEEKDAYS.map(function (w) { return '<span>' + w + '</span>'; }).join('') + '</div>' +
            '<div class="jdp-grid"></div>' +
            '<button type="button" class="jdp-today-btn">امروز</button>';
        popup.querySelector('[data-nav="prev"]').addEventListener('click', function () { shift(-1); });
        popup.querySelector('[data-nav="next"]').addEventListener('click', function () { shift(1); });
        popup.querySelector('.jdp-today-btn').addEventListener('click', function () {
            var t = todayJalali();
            choose(t.y, t.m, t.d);
        });
        popup.querySelector('.jdp-grid').addEventListener('click', function (e) {
            var cell = e.target.closest('.jdp-day');
            if (cell) choose(state.y, state.m, +cell.dataset.d);
        });
    }

    function shift(delta) {
        state.m += delta;
        if (state.m < 1) { state.m = 12; state.y -= 1; }
        if (state.m > 12) { state.m = 1; state.y += 1; }
        render();
    }

    function render() {
        var today = todayJalali();
        popup.querySelector('.jdp-label').textContent = MONTHS[state.m - 1] + ' ' + state.y;
        var total = daysInMonth(state.y, state.m);
        var g = d2g(j2d(state.y, state.m, 1));
        var offset = (new Date(g[0], g[1] - 1, g[2]).getDay() + 1) % 7;
        var html = '';
        for (var i = 0; i < offset; i++) html += '<span class="jdp-cell"></span>';
        for (var d = 1; d <= total; d++) {
            var cls = 'jdp-cell jdp-day';
            if (state.sel && state.sel.y === state.y && state.sel.m === state.m && state.sel.d === d) cls += ' selected';
            if (today.y === state.y && today.m === state.m && today.d === d) cls += ' today';
            html += '<span class="' + cls + '" data-d="' + d + '">' + d + '</span>';
        }
        popup.querySelector('.jdp-grid').innerHTML = html;
    }

    function choose(y, m, d) {
        state.input.value = fmt(y, m, d);
        state.input.dispatchEvent(new Event('input', { bubbles: true }));
        state.input.dispatchEvent(new Event('change', { bubbles: true }));
        close();
    }

    function open(input) {
        if (!popup) buildPopup();
        var wrap = input.closest('.jdp-wrap');
        var parsed = parse(input.value) || todayJalali();
        state.input = input;
        state.y = parsed.y;
        state.m = parsed.m;
        state.sel = parse(input.value);
        render();
        wrap.appendChild(popup);
        popup.hidden = false;
        popup.classList.remove('jdp-flip-up');
        var rect = wrap.getBoundingClientRect();
        var height = popup.offsetHeight || 320;
        if (window.innerHeight - rect.bottom < height + 12 && rect.top > height + 12) {
            popup.classList.add('jdp-flip-up');
        }
    }

    function close() {
        if (popup) popup.hidden = true;
    }

    function init(input) {
        if (input.closest('.jdp-wrap')) return;
        var wrap = document.createElement('div');
        wrap.className = 'jdp-wrap';
        var row = document.createElement('div');
        row.className = 'jdp-row';
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'jdp-btn';
        button.textContent = '📅';
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(row);
        row.appendChild(input);
        row.appendChild(button);
        button.addEventListener('click', function (e) {
            e.preventDefault();
            open(input);
        });
        input.addEventListener('focus', function () { open(input); });
        input.addEventListener('click', function () { if (!popup || popup.hidden || state.input !== input) open(input); });
    }

    document.addEventListener('mousedown', function (e) {
        if (!popup || popup.hidden) return;
        if (popup.contains(e.target)) return;
        var wrap = state.input && state.input.closest('.jdp-wrap');
        if (wrap && wrap.contains(e.target)) return;
        close();
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('input[data-jalali-datepicker]').forEach(init);
    });
})();
