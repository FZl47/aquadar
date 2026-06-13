function redirect(url) {
    window.location.href = url
}

function sendAjax({url, data, method = 'post', success, error, error_msg}) {

    success = success || function (response) {
    }
    error = error || function (response) {
        createNotify(
            {
                title: 'ارور',
                message: error_msg || 'مشکلی در ارسال درخواست وجود دارد لطفا اتصال خود را بررسی کنید',
                theme: 'error'
            }
        )
    }
    $.ajax(
        {
            url: url,
            data: JSON.stringify(data),
            type: method,
            headers: {
                'X-CSRFToken': CSRF_TOKEN
            },
            success: function (response) {
                success(response)
            },
            failed: function (response) {
                error(response)
            },
            error: function (response) {
                error(response)
            }
        }
    )
}

function getUrlParameter(sParam) {
    var sPageURL = window.location.search.substring(1),
        sURLVariables = sPageURL.split('&'),
        sParameterName,
        i;
    for (i = 0; i < sURLVariables.length; i++) {
        sParameterName = sURLVariables[i].split('=');

        if (sParameterName[0] === sParam) {
            return sParameterName[1] === undefined ? true : decodeURIComponent(sParameterName[1]);
        }
    }
    return false;
}

function randomString(length = 15) {
    let result = '';
    const characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    const charactersLength = characters.length;
    let counter = 0;
    while (counter < length) {
        result += characters.charAt(Math.floor(Math.random() * charactersLength));
        counter += 1;
    }
    return result;
}


function setCookie(name, value, days) {
    var expires = "";
    if (days) {
        var date = new Date();
        date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
        expires = "; expires=" + date.toUTCString();
    }
    document.cookie = name + "=" + (value || "") + expires + "; path=/";
}

function getCookie(name) {
    var nameEQ = name + "=";
    var ca = document.cookie.split(';');
    for (var i = 0; i < ca.length; i++) {
        var c = ca[i];
        while (c.charAt(0) == ' ') c = c.substring(1, c.length);
        if (c.indexOf(nameEQ) == 0) return c.substring(nameEQ.length, c.length);
    }
    return null;
}

function removeCookie(name) {
    document.cookie = name + '=; Path=/; Expires=Thu, 01 Jan 1970 00:00:01 GMT;';
}


function createLoading(element, options = {
    size: 'normal',
    color: '#1ee696',
    fill: null

}) {
    if (element.classList.contains('loading-element-parent')) {
        return
    }
    let loading = document.createElement('div')
    loading.className = `loading-element loading-circle-${options.size}`
    let color = options.color
    loading.style = `
        border-top-color:${color};
        border-right-color:${color};
    `
    let loading_blur = document.createElement('div')
    if (options.fill) {
        loading_blur.style = `
            background:${options.fill};
        `
        loading_blur.classList.add('fill')
    }
    loading_blur.className = 'loading-blur-element'
    element.append(loading_blur)
    element.append(loading)
    element.classList.add('loading-element-parent')
    element.setAttribute('disabled', 'disabled')
}

function removeLoading(element) {
    try {
        element.querySelector('.loading-element').remove()
        element.querySelector('.loading-blur-element').remove()
        element.classList.remove('loading-element-parent')
        element.removeAttribute('disabled')
    } catch (e) {

    }
}


let all_datetime_convert = document.querySelectorAll('.datetime-convert')
if (LANGUAGE_CODE == 'en') {
    all_datetime_convert = []
}
for (let dt_el of all_datetime_convert) {
    let dt = dt_el.innerHTML || dt_el.value
    dt_el.setAttribute('datetime', dt)
    dt_el.dir = 'ltr'

    let options = {}

    let only_date = dt_el.getAttribute('only-date') || 'false'
    if (only_date == 'false') {
        options = {
            hour: '2-digit',
            minute: '2-digit',
        }
    }

    let dt_persian = new Date(dt).toLocaleDateString('fa-IR', options);
    dt_persian = dt_persian.replaceAll('/', '-')
    if (dt_persian != 'Invalid Date') {
        dt_el.innerHTML = dt_persian
        dt_el.value = dt_persian
    }
}

let all_spread_price = document.querySelectorAll('.spread-price')
for (let el of all_spread_price) {
    let price = el.innerHTML
    el.innerHTML = numberWithCommas(price)
}

function numberWithCommas(x, decimals = 3) {
    if (LANGUAGE_CODE == 'fa') {
        decimals = 0
    }
    let num = Number(x);
    num = num.toFixed(decimals);
    return num.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}


// ---


let container_select_choices = document.querySelectorAll('.container-select-choices')

$('.container-select-choices input[type="radio"]').on('change', function (e) {
    let inp = e.currentTarget
    let choices = inp.parentNode.parentNode
    choices.setAttribute('choice-val', inp.value)

});


// price elements
document.querySelectorAll('.price-el').forEach((el) => {
    let p = el.innerText
    el.setAttribute('price-val', p)
    let formatted = p.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    let n = formatted.split('.')[0]
    let decimal = formatted.split('.')[1]
    let currency_label = el.getAttribute('currency-label') || 'ریال'

    // if (decimal && LANGUAGE_CODE != 'fa') {
    //     el.innerHTML = `${n}<span class="decimal">.${decimal}</span>`
    // } else {
    //     el.innerHTML = `${n}`
    // }

    el.innerHTML = `${n}`

    el.innerHTML += ` <span class="currency-label">${currency_label}</span> `
    if (LANGUAGE_CODE == 'en') {
        el.dir = 'rtl'
    }
})

document.querySelectorAll('.num-el').forEach((el) => {
    // TODO: fix numbers with decimal places
    let p = el.innerText
    el.setAttribute('num-val', p)

    let formatted = p.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    let n = formatted.split('.')[0]
    let decimal = formatted.split('.')[1]
    // if (decimal && LANGUAGE_CODE != 'fa') {
    //     el.innerHTML = `${n}.<span class="decimal">${decimal}</span>`
    // } else {
    //     el.innerHTML = n
    // }
    el.innerHTML = n
})

function getRandomColor() {
    var letters = '0123456789ABCDEF'.split('');
    var color = '#';
    for (var i = 0; i < 6; i++) {
        color += letters[Math.floor(Math.random() * 16)];
    }
    return color;
}

// random-bg
document.querySelectorAll('.random-bg').forEach(function (el) {
    el.style.background = getRandomColor()
})


function toggleRelatedField(fieldId, show = true) {
    const field = document.getElementById(fieldId);
    if (show) {
        field.classList.remove('d-none');
    } else {
        field.classList.add('d-none');
    }
}

// add query params
let query_params = (new URL(location)).searchParams;
document.querySelectorAll('.add-params-to-href').forEach(function (el) {
    let href = el.getAttribute('href')
    let href_params = new URLSearchParams(href)
    for (let p of query_params) {
        let k = p[0]
        let v = String(p[1])
        if (href.includes(k) === false) {
            href_params.set(k, v)
        }
    }
    let params = href_params.toString()
    if (params.indexOf('?') == -1) {
        params = '?' + params
    }
    el.setAttribute('href', params)
})

document.querySelectorAll('.add-params-to-form').forEach(function (form) {
    for (let p of query_params) {
        let name = p[0]
        let value = p[1]
        if (!form.elements[name]) {
            let inp = document.createElement('input')
            inp.type = 'hidden'
            inp.name = name
            inp.value = value
            form.appendChild(inp)
        }
    }
})

// select option by filter query search
document.querySelectorAll('.select-by-filter').forEach(function (select) {
    let filter_name = select.name || select.getAttribute('filter-name')
    let filter_value = getUrlParameter(filter_name)
    try {
        select.querySelector(`[value="${filter_value}"]`).setAttribute('selected', 'selected')
    } catch (e) {
    }
})

// select option by value select
document.querySelectorAll('.select-by-value').forEach(function (select) {
    let value = select.getAttribute('value') || 'false'
    if (value == 'False') {
        value = 'false'
    } else if (value == 'True') {
        value = 'true'
    }
    try {
        select.querySelector(`option[value="${value}"]`).setAttribute('selected', 'selected')
    } catch (e) {
    }
})

// theme(dark mode)

let _btn_switch_theme = document.querySelector('.dark-switch')
try {
    _btn_switch_theme.addEventListener('click', function (el) {
        el.preventDefault()
        if (el.currentTarget.classList.contains('active')) {
            setThemeMode('light')
        } else {
            setThemeMode('dark')
        }
    })
} catch (e) {
}

function setThemeMode(theme) {
    try {
        setCookie('theme-mode', theme)
        if (theme === 'light') {
            _btn_switch_theme.classList.remove('active')
            document.body.classList.remove('dark-mode')
        } else {
            _btn_switch_theme.classList.add('active')
            document.body.classList.add('dark-mode')
        }
    } catch (e) {
    }
}

// initial theme
setThemeMode(getCookie('theme-mode') || 'light')


// view files
let view_file_elements = document.getElementsByClassName("view-file");

for (var i = 0; i < view_file_elements.length; i++) {
    view_file_elements[i].addEventListener('click', function () {
        var fileUrl = this.getAttribute('href');
        window.open(fileUrl, '_blank');
    });
}


function addParamsToUrl(params) {
    var currentUrl = window.location.href;
    var newUrl = new URL(currentUrl);

    for (var key in params) {
        if (params.hasOwnProperty(key)) {
            newUrl.searchParams.set(key, params[key]);
        }
    }

    history.pushState({}, '', newUrl);
}

function inactivityTime() {
    let time;
    window.onload = resetTimer;
    document.onmousemove = resetTimer;
    document.onkeydown = resetTimer;

    function logout() {
        window.location.href = LOGOUT_URL
    }

    function resetTimer() {
        clearTimeout(time);
        let time_amount = 1000 * 300 * 4 * 6 // 120 minutes
        time = setTimeout(logout, time_amount)
    }
}


document.querySelectorAll('.form-number').forEach(function (el) {

    function createLabel(input) {
        let cnt = input.parentElement
        let element = document.createElement('span')
        let inp_val = input.value || 0
        inp_val = numberWithCommas(inp_val)

        let n = inp_val.split('.')[0]
        let decimal = inp_val.split('.')[1]

        element.innerHTML = `${n} ${CURRENCY_LABEL}`
        // element.innerHTML = `${inp_val}`
        element.classList.add('number-label')

        let parent = input.getAttribute('form-number-el')
        if (parent) {
            cnt = cnt.parentElement
        }

        cnt.append(element)
    }

    createLabel(el)

    el.addEventListener('input', function (e) {
        let n = numberWithCommas(this.value) || 0
        n = n.split('.')[0]
        let decimal = n.split('.')[1]
        this.parentElement.parentElement.querySelector('.number-label').innerHTML = `${n} ${CURRENCY_LABEL}`
        // this.parentElement.parentElement.querySelector('.number-label').innerHTML = `${n}`
    })

})


document.querySelectorAll('.form-number-child').forEach(function (el) {

    let input = el.querySelector('input')
    let has_currency = el.getAttribute('data-currency') || 'true'

    function createLabel(input) {
        let cnt = input.parentElement.parentElement
        let element = document.createElement('span')
        let inp_val = input.value || 0
        inp_val = numberWithCommas(inp_val)


        if (has_currency == 'true') {
            element.innerHTML = `${inp_val} ${CURRENCY_LABEL}`
        } else {
            element.innerHTML = `${inp_val}`
        }

        element.classList.add('number-label')
        cnt.append(element)
    }

    createLabel(input)

    input.addEventListener('input', function (e) {
        let n = numberWithCommas(this.value) || 0
        let has_currency = this.parentElement.getAttribute('data-currency') || 'true'

        if (has_currency == 'true') {
            this.parentElement.parentElement.querySelector('.number-label').innerHTML = `${n} ${CURRENCY_LABEL}`
        } else {
            this.parentElement.parentElement.querySelector('.number-label').innerHTML = `${n}`
        }
    })
})

document.querySelectorAll('.form-number-split').forEach(function (el) {

    function createLabel(input) {
        let cnt = input.parentElement
        let element = document.createElement('span')
        let inp_val = input.value || 0
        inp_val = numberWithCommas(inp_val)

        element.innerHTML = `${inp_val}`
        element.classList.add('number-label')
        cnt.append(element)
    }

    createLabel(el)

    el.addEventListener('input', function (e) {
        let n = numberWithCommas(this.value) || 0
        this.parentElement.querySelector('.number-label').innerHTML = `${n}`
    })

})

document.querySelectorAll('.form-number-split-child').forEach(function (el) {

    let input = el.querySelector('input')

    function createLabel(input) {
        let cnt = input.parentElement.parentElement
        let element = document.createElement('span')
        let inp_val = input.value || 0
        inp_val = numberWithCommas(inp_val)

        element.innerHTML = `${inp_val}`
        element.classList.add('number-label')
        cnt.append(element)
    }

    createLabel(input)

    input.addEventListener('input', function (e) {
        let n = numberWithCommas(this.value) || 0
        this.parentElement.parentElement.querySelector('.number-label').innerHTML = `${n}`
    })

})


document.querySelectorAll('.number-abs').forEach(function (el) {
    let value = parseFloat(el.textContent || el.value || 0);

    let absValue = Math.abs(value);

    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
        el.value = absValue;
    } else {
        el.textContent = absValue;
    }
});


function timeAgo(datetimeStr) {

    const date = new Date(datetimeStr.replace(' ', 'T'));
    const now = new Date();

    const diffMs = now - date;
    const diffSeconds = Math.floor(diffMs / 1000);
    const diffMinutes = Math.floor(diffSeconds / 60);
    const diffHours = Math.floor(diffMinutes / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffSeconds < 60) {
        return 'چند ثانیه پیش';
    }
    if (diffMinutes < 60) {
        return diffMinutes + ' دقیقه پیش';
    }
    if (diffHours < 24) {
        return diffHours + ' ساعت پیش';
    }
    if (diffDays < 30) {
        return diffDays + ' روز پیش';
    }

    const diffMonths = Math.floor(diffDays / 30);
    if (diffMonths < 12) {
        return diffMonths + ' ماه پیش';
    }

    const diffYears = Math.floor(diffDays / 365);
    return diffYears + ' سال پیش';
}


document.querySelectorAll('.time-ago').forEach(function (el) {
    let t = timeAgo(el.innerText)
    el.innerText = t
})


function updateDurationOutlets() {
    let outlets_duration = document.querySelectorAll('[outlet-duration="running"]')
    setInterval(function (el) {
        for (let outlet of outlets_duration) {
            let sec = parseInt(outlet.innerText)
            outlet.innerText = sec + 1
        }
    }, 1000)
}

updateDurationOutlets()