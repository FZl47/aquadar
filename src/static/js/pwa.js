// pwa
let deferredPrompt;

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    document.getElementById('addToHomeScreen').style.display = 'block';
});


document.getElementById('addToHomeScreen').addEventListener('click', () => {

    if (deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then((choiceResult) => {
            if (choiceResult.outcome === 'accepted') {
                document.querySelector('.btn-add-to-home').classList.add('fade')
                console.log('کاربر افزودن به صفحه اصلی را پذیرفت.');
            } else {
                console.log('کاربر افزودن به صفحه اصلی را رد کرد.');
            }
            deferredPrompt = null;
        });
    }
});

function isPwa() {
    return ["fullscreen", "standalone", "minimal-ui"].some(
        (displayMode) => window.matchMedia('(display-mode: ' + displayMode + ')').matches
    );
}

try {
    if (isPwa()){
        document.getElementById('addToHomeScreen').style.display = 'none'
    }
}catch (e){}