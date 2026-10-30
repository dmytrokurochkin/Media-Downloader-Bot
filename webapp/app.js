const tg = window.Telegram.WebApp;

// localStorage у деяких WebView кидає виняток (приватний режим, вимкнене сховище),
// тож усі звернення до нього — через ці обгортки.
function storageGet(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
}
function storageSet(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* не критично */ }
}

let hapticEnabled = storageGet('hapticEnabled') !== 'false';

// Імена й домени в лідерборді та пошуку — це текст, який ввели користувачі
// (ім'я в Telegram може містити будь-які символи, зокрема HTML). Тому дані
// вставляються ЛИШЕ через textContent; innerHTML з ними = stored XSS, а з
// Mini App, запущеної з reply-кнопки, скрипт міг би слати боту sendData від
// імені жертви.
function createEl(tag, options) {
    const node = document.createElement(tag);
    const opts = options || {};
    if (opts.className) node.className = opts.className;
    if (opts.text !== undefined && opts.text !== null) node.textContent = String(opts.text);
    if (opts.style) node.setAttribute('style', opts.style);
    return node;
}

function showListMessage(list, text, style) {
    list.textContent = '';
    list.appendChild(createEl('li', { text: text, style: style }));
}

// initData іде в заголовку, а не в query string: query потрапляє в access-логи
// сервера й ngrok, а initData дійсний 24 години.
function apiHeaders() {
    return {
        'ngrok-skip-browser-warning': 'true',
        'Authorization': 'tma ' + (tg.initData || '')
    };
}

function triggerHaptic(style) {
    if (hapticEnabled) {
        try { tg.HapticFeedback.impactOccurred(style); } catch(e){}
    }
}

// Extract URL parameters
const urlParams = new URLSearchParams(window.location.search);
let lang = urlParams.get('l') || 'uk';
const tier = urlParams.get('t') || 'free';
const used = parseInt(urlParams.get('u') || '0');
const limitDaily = parseInt(urlParams.get('lmd') || '0');
const limitPlaylist = parseInt(urlParams.get('lmp') || '0');
const limitSize = parseInt(urlParams.get('lms') || '0');
const topUsersStr = urlParams.get('tu') || '';
const topSitesStr = urlParams.get('ts') || '';
const botUsername = urlParams.get('b') || '';
const userNameParam = urlParams.get('nm') || '';
const vipUntilTs = parseInt(urlParams.get('vu') || '0');
const apiUrl = urlParams.get('api') || 'http://127.0.0.1:8080/api';
const totalBytes = parseInt(urlParams.get('tb') || '0');
const totalDownloads = parseInt(urlParams.get('td') || '0');
const badgesStr = urlParams.get('bdg') || '';
const userBadges = badgesStr ? badgesStr.split(',') : [];

const ALL_BADGES = {
    'first_blood': {
        icon: '🩸',
        max: 1,
        format: (val, max) => `${val} / ${max}`,
        calc: (profile) => Math.min(profile.downloads_count || 0, 1)
    },
    'heavy_lifter': {
        icon: '🏋️‍♂️',
        max: 1024 * 1024 * 1024,
        format: (val, max) => {
            const valMb = Math.round(val / (1024 * 1024));
            const maxMb = Math.round(max / (1024 * 1024));
            return `${valMb} MB / ${maxMb} MB`;
        },
        calc: (profile) => Math.min(profile.total_bytes_downloaded || 0, 1024 * 1024 * 1024)
    },
    'night_owl': {
        icon: '🦉',
        max: 1,
        format: (val, max) => `${val} / ${max}`,
        calc: (profile) => (profile.badges || []).includes('night_owl') ? 1 : 0
    }
};

// Settings params
const currentGuestQuality = urlParams.get('gq') || 'best';
const currentAnonymous = urlParams.get('anon') === '1';
const currentTheme = urlParams.get('th') || 'standard';
const ownedThemes = (urlParams.get('ow') || 'standard').split(',');
const currentWatermarkPos = urlParams.get('wp') || 'bottom_right';

// Get user data from Telegram SDK if available, fallback to URL param
let userFirstName = userNameParam || 'User';
let userPhotoUrl = null;
if (tg.initDataUnsafe && tg.initDataUnsafe.user) {
    if (tg.initDataUnsafe.user.first_name) {
        userFirstName = tg.initDataUnsafe.user.first_name;
    }
    if (tg.initDataUnsafe.user.photo_url) {
        userPhotoUrl = tg.initDataUnsafe.user.photo_url;
    }
}

// Set up UI
document.addEventListener('DOMContentLoaded', () => {
    const isMobile = ['android', 'android_ar', 'android_x', 'ios', 'ipad'].includes(tg.platform);
    
    if (isMobile) {
        if (tg.expand) {
            tg.expand(); // Expand to full height
        }
        if (tg.requestFullscreen) {
            try {
                tg.requestFullscreen(); // Force modern Fullscreen mode if supported
            } catch (e) {
                console.error("Fullscreen not supported or failed", e);
            }
        }
    }
    bindUiEvents();
    applyTranslations();
    renderProfile();
    renderLeaderboards();
    setupSearch();
    
    // Apply current theme
    document.body.setAttribute('data-theme', currentTheme);
    
    // Tell Telegram app is ready
    tg.ready();
    
    const toggle = document.getElementById('vibrationToggle');
    if (toggle) {
        toggle.checked = hapticEnabled;
        toggle.addEventListener('change', (e) => {
            hapticEnabled = e.target.checked;
            storageSet('hapticEnabled', hapticEnabled);
            triggerHaptic('medium');
        });
    }

    // Pre-fill settings form
    const selLang = document.getElementById('settings_language');
    if (selLang) {
        selLang.value = lang;
        selLang.addEventListener('change', (e) => {
            lang = e.target.value;
            applyTranslations();
        });
    }

    const selQuality = document.getElementById('settings_guest_quality');
    if (selQuality) selQuality.value = currentGuestQuality;

    const toggleAnon = document.getElementById('settings_anonymous');
    if (toggleAnon) toggleAnon.checked = currentAnonymous;

    const selTheme = document.getElementById('settings_theme');
    if (selTheme) {
        selTheme.value = currentTheme;
        selTheme.addEventListener('change', (e) => {
            const btn = document.getElementById('btn_save_settings');
            if (btn) {
                if (!ownedThemes.includes(e.target.value)) {
                    btn.innerText = getText(lang, 'buy_theme_btn');
                } else {
                    btn.innerText = getText(lang, 'btn_save_settings') || "Save settings";
                }
            }
        });
    }

    const selWatermarkPos = document.getElementById('settings_watermark_pos');
    if (selWatermarkPos) selWatermarkPos.value = currentWatermarkPos;
    
    // Initialize custom dropdowns
    if (typeof initCustomSelects === 'function') {
        initCustomSelects();
    }
    
    // Interactive spotlight and prism effect
    let isCursorUpdating = false;
    let cursorEvent = null;

    const updateCursorPos = () => {
        if (!cursorEvent) {
            isCursorUpdating = false;
            return;
        }
        
        let clientX = cursorEvent.clientX;
        let clientY = cursorEvent.clientY;
        if (cursorEvent.touches && cursorEvent.touches.length > 0) {
            clientX = cursorEvent.touches[0].clientX;
            clientY = cursorEvent.touches[0].clientY;
        }
        
        const glassElements = document.querySelectorAll('.glass');
        for (let i = 0; i < glassElements.length; i++) {
            const card = glassElements[i];
            // Skip elements that are not visible to save expensive getBoundingClientRect calls
            if (card.offsetWidth === 0 && card.offsetHeight === 0) continue;
            
            const rect = card.getBoundingClientRect();
            
            // Only update if the card is in the viewport vertically
            if (rect.bottom < 0 || rect.top > window.innerHeight) continue;
            
            const x = clientX - rect.left;
            const y = clientY - rect.top;
            
            const rotX = -((y / rect.height) - 0.5) * 12;
            const rotY = ((x / rect.width) - 0.5) * 12;
            
            card.style.setProperty('--mouse-x', `${x}px`);
            card.style.setProperty('--mouse-y', `${y}px`);
            card.style.setProperty('--rot-x', `${rotX}deg`);
            card.style.setProperty('--rot-y', `${rotY}deg`);
        }
        isCursorUpdating = false;
    };

    const scheduleCursorUpdate = (e) => {
        cursorEvent = e;
        if (!isCursorUpdating) {
            isCursorUpdating = true;
            requestAnimationFrame(updateCursorPos);
        }
    };

    document.body.addEventListener('mousemove', scheduleCursorUpdate);
    document.body.addEventListener('touchmove', scheduleCursorUpdate, {passive: true});
    
    // Add touch/mouse class so the 3D effect is visible while pressing
    document.querySelectorAll('.glass').forEach(card => {
        const handleDown = (e) => {
            if (e.target.closest('button, .btn, .badge-item, select, input, label, .custom-select-trigger, .custom-select-option, .switch, a')) return;
            scheduleCursorUpdate(e);
            card.classList.add('touching');
            if (card.classList.contains('card')) {
                try { 
                    triggerHaptic('heavy'); 
                    setTimeout(() => triggerHaptic('heavy'), 20);
                    setTimeout(() => triggerHaptic('heavy'), 40);
                } catch(err){}
            }
        };
        const handleUp = () => {
            card.classList.remove('touching');
            if (card.classList.contains('card')) {
                try { 
                    triggerHaptic('heavy'); 
                } catch(err){}
            }
        };
        const handleCancel = () => {
            card.classList.remove('touching');
        };
        
        card.addEventListener('touchstart', handleDown, {passive: true});
        card.addEventListener('touchend', handleUp);
        card.addEventListener('touchcancel', handleCancel);
        
        card.addEventListener('mousedown', handleDown);
        card.addEventListener('mouseup', handleUp);
        card.addEventListener('mouseleave', handleCancel);
    });

    // Swipe navigation logic
    let touchStartX = 0;
    let touchStartY = 0;
    let lastSwipeVibrateX = 0;
    const swipeThreshold = 40; // minimum distance in px
    
    document.addEventListener('touchstart', (e) => {
        touchStartX = e.changedTouches[0].screenX;
        touchStartY = e.changedTouches[0].screenY;
        lastSwipeVibrateX = 0;
    }, {passive: true});
    
    document.addEventListener('touchmove', (e) => {
        if (!touchStartX) return;
        const currentX = e.changedTouches[0].screenX;
        const currentY = e.changedTouches[0].screenY;
        const deltaX = Math.abs(touchStartX - currentX);
        const deltaY = Math.abs(touchStartY - currentY);
        
        // Only trigger crunch if horizontal movement is dominant
        if (deltaX > deltaY && (deltaX - lastSwipeVibrateX > 15)) {
            try { triggerHaptic('medium'); } catch(e){} // crunchy zipper effect
            lastSwipeVibrateX = deltaX;
        }
    }, {passive: true});

    document.addEventListener('touchend', (e) => {
        const touchEndX = e.changedTouches[0].screenX;
        const touchEndY = e.changedTouches[0].screenY;
        
        const deltaX = touchStartX - touchEndX;
        const deltaY = Math.abs(touchStartY - touchEndY);
        
        // Prevent swipe if vertical scrolling was dominant
        if (Math.abs(deltaX) > deltaY && Math.abs(deltaX) > swipeThreshold) {
            
            // Prevent swipe if a modal is open
            const publicModal = document.getElementById('publicProfileModal');
            const badgeModal = document.getElementById('badgeInfoModal');
            if ((publicModal && publicModal.style.display !== 'none') || 
                (badgeModal && badgeModal.style.display !== 'none')) {
                return;
            }

            const tabs = ['profile', 'leaderboard', 'store', 'clipper', 'audio-editor', 'settings'];
            let currentIndex = 0;
            document.querySelectorAll('.section').forEach((sec, idx) => {
                if (sec.classList.contains('active')) currentIndex = idx;
            });
            
            let targetIndex = currentIndex;
            if (deltaX > 0) {
                // Swiped left -> Next tab
                targetIndex = Math.min(tabs.length - 1, currentIndex + 1);
            } else {
                // Swiped right -> Prev tab
                targetIndex = Math.max(0, currentIndex - 1);
            }
            
            if (targetIndex !== currentIndex) {
                const navItems = document.querySelectorAll('.nav-item');
                switchTab(tabs[targetIndex], navItems[targetIndex]);
            }
        }
    });
    
    if (typeof updateNavVisibility === 'function') {
        updateNavVisibility();
    }

    // Prevent scrolling while modals are open to fix lag
    const modals = document.querySelectorAll('.modal');
    modals.forEach(m => {
        m.addEventListener('touchmove', (e) => {
            // Prevent default scroll on the modal overlay to fix background lag
            e.preventDefault();
        }, { passive: false });
    });
});

// Обробники подій вішаються тут, а не атрибутами onclick в index.html:
// Content-Security-Policy сторінки забороняє inline-скрипти (захист від XSS).
function bindUiEvents() {
    const bindClick = (id, handler) => {
        const node = document.getElementById(id);
        if (node) node.addEventListener('click', handler);
    };
    bindClick('buyVipBtn', buyVip);
    bindClick('btn_smart_trim', submitSmartTrim);
    bindClick('btn_audio_editor', submitAudioEditor);
    bindClick('btn_save_settings', saveSettings);
    bindClick('closeProfileModalBtn', closeProfileModal);
    bindClick('closeBadgeModalBtn', closeBadgeModal);

    document.querySelectorAll('.nav-item[data-tab]').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab, btn));
    });

    const badgeModal = document.getElementById('badgeInfoModal');
    if (badgeModal) {
        badgeModal.addEventListener('click', (e) => {
            if (e.target === badgeModal) closeBadgeModal();
        });
    }

    const bindFileName = (inputId, labelId) => {
        const input = document.getElementById(inputId);
        const label = document.getElementById(labelId);
        if (!input || !label) return;
        input.addEventListener('change', () => {
            label.textContent = input.files.length ? input.files[0].name : getText(lang, 'no_file_chosen');
        });
    };
    bindFileName('editor_cover', 'editor_cover_name');
    bindFileName('settings_watermark_file', 'settings_watermark_name');
}

function setTextById(id, key) {
    const node = document.getElementById(id);
    if (node) node.innerText = getText(lang, key);
}

function setPlaceholderById(id, key) {
    const node = document.getElementById(id);
    if (node) node.placeholder = getText(lang, key);
}

function applyTranslations() {
    // Статичні підписи, що раніше були захардкоджені українською в index.html.
    setTextById('label_editor_url', 'label_editor_url');
    setTextById('label_editor_title', 'label_editor_title');
    setTextById('label_editor_artist', 'label_editor_artist');
    setTextById('label_editor_album', 'label_editor_album');
    setTextById('label_editor_cover', 'label_editor_cover');
    setTextById('label_editor_cover_hint', 'label_editor_cover_hint');
    setTextById('label_modal_downloads', 'modal_downloads');
    setTextById('label_modal_traffic', 'modal_traffic');
    setTextById('label_modal_badges', 'label_badges_main');
    setPlaceholderById('userSearchInput', 'search_placeholder');
    setPlaceholderById('editor_title', 'placeholder_track_title');
    setPlaceholderById('editor_artist', 'placeholder_track_artist');
    setPlaceholderById('editor_album', 'placeholder_track_album');

    document.getElementById('pageTitle').innerText = getText(lang, 'title_profile');
    document.getElementById('label_stat_downloads').innerText = getText(lang, 'stat_daily_limit');
    document.getElementById('label_limit_size').innerText = getText(lang, 'limit_size');
    document.getElementById('label_limit_playlist').innerText = getText(lang, 'limit_playlist');
    document.getElementById('label_top_users').innerText = getText(lang, 'top_users');
    document.getElementById('label_top_sites').innerText = getText(lang, 'top_sites');
    document.getElementById('label_tier_vip_store').innerText = getText(lang, 'tier_vip');
    document.getElementById('buyVipBtn').innerText = getText(lang, 'buy_vip_btn');
    
    document.getElementById('label_sub_active').innerText = getText(lang, 'subscription_active');
    document.getElementById('label_sub_expires').innerText = getText(lang, 'subscription_expires');
    document.getElementById('label_sub_days').innerText = getText(lang, 'subscription_days_left');
    
    if (tier === 'pro') {
        document.getElementById('label_vip_desc_1').innerText = getText(lang, 'pro_desc_1');
        document.getElementById('label_vip_desc_2').innerText = getText(lang, 'pro_desc_2');
    } else {
        document.getElementById('label_vip_desc_1').innerText = getText(lang, 'vip_desc_1');
        document.getElementById('label_vip_desc_2').innerText = getText(lang, 'vip_desc_2');
    }
    document.getElementById('label_vip_desc_3').innerText = getText(lang, 'vip_desc_3');
    document.getElementById('label_vip_desc_4').innerText = getText(lang, 'vip_desc_4');
    
    document.getElementById('tab_profile').innerText = getText(lang, 'title_profile');
    document.getElementById('tab_leaderboard').innerText = getText(lang, 'title_leaderboard');
    document.getElementById('tab_store').innerText = getText(lang, 'title_store');
    
    const labelBadgesMain = document.getElementById('label_badges_main');
    if (labelBadgesMain) labelBadgesMain.innerText = getText(lang, 'label_badges_main');
    
    const tabSettingsEl = document.getElementById('tab_settings');
    if (tabSettingsEl) tabSettingsEl.innerText = getText(lang, 'title_settings');
    
    const tabClipperEl = document.getElementById('tab_clipper');
    if (tabClipperEl) tabClipperEl.innerText = getText(lang, 'title_clipper');
    const tabAudioEditorEl = document.getElementById('tab_audio_editor');
    if (tabAudioEditorEl) tabAudioEditorEl.innerText = getText(lang, 'title_audio_editor');
    
    document.getElementById('pageTitle').innerText = getText(lang, 'title_profile');
    
    // Settings translations
    const labelSettingsMain = document.getElementById('label_settings_main');
    if (labelSettingsMain) labelSettingsMain.innerText = getText(lang, 'label_settings_main');
    
    const labelLanguage = document.getElementById('label_language');
    if (labelLanguage) labelLanguage.innerText = getText(lang, 'label_language');
    
    const labelGuestQuality = document.getElementById('label_guest_quality');
    if (labelGuestQuality) labelGuestQuality.innerText = getText(lang, 'label_guest_quality');
    
    const optQualityBest = document.getElementById('opt_quality_best');
    if (optQualityBest) optQualityBest.innerText = getText(lang, 'opt_quality_best');

    const labelTheme = document.getElementById('label_theme');
    if (labelTheme) labelTheme.innerText = getText(lang, 'label_theme');
    
    const optThemeStandard = document.getElementById('opt_theme_standard');
    if (optThemeStandard) optThemeStandard.innerText = getText(lang, 'opt_theme_standard');
    
    const optThemeNeon = document.getElementById('opt_theme_neon');
    if (optThemeNeon) optThemeNeon.innerText = getText(lang, 'opt_theme_neon');
    
    const optThemeRetro = document.getElementById('opt_theme_retro');
    if (optThemeRetro) optThemeRetro.innerText = getText(lang, 'opt_theme_retro');
    
    const labelAnon = document.getElementById('label_anonymous');
    if (labelAnon) labelAnon.innerText = getText(lang, 'label_anonymous');
    
    const labelAnonDesc = document.getElementById('label_anonymous_desc');
    if (labelAnonDesc) labelAnonDesc.innerText = getText(lang, 'label_anonymous_desc');
    
    const labelVibration = document.getElementById('label_vibration');
    if (labelVibration) labelVibration.innerText = getText(lang, 'vibration');
    
    const labelBranding = document.getElementById('label_branding');
    if (labelBranding) labelBranding.innerText = getText(lang, 'label_branding');
    
    const labelWatermarkPos = document.getElementById('label_watermark_pos');
    if (labelWatermarkPos) labelWatermarkPos.innerText = getText(lang, 'label_watermark_pos');
    
    const optPosTl = document.getElementById('opt_pos_tl');
    if (optPosTl) optPosTl.innerText = getText(lang, 'opt_pos_tl');
    
    const optPosTr = document.getElementById('opt_pos_tr');
    if (optPosTr) optPosTr.innerText = getText(lang, 'opt_pos_tr');
    
    const optPosBl = document.getElementById('opt_pos_bl');
    if (optPosBl) optPosBl.innerText = getText(lang, 'opt_pos_bl');
    
    const optPosBr = document.getElementById('opt_pos_br');
    if (optPosBr) optPosBr.innerText = getText(lang, 'opt_pos_br');
    
    const labelWatermarkFile = document.getElementById('label_watermark_file');
    if (labelWatermarkFile) labelWatermarkFile.innerText = getText(lang, 'label_watermark_file');
    
    const labelWatermarkHint = document.getElementById('label_watermark_hint');
    if (labelWatermarkHint) labelWatermarkHint.innerText = getText(lang, 'label_watermark_hint');
    
    const btnSaveSettings = document.getElementById('btn_save_settings');
    if (btnSaveSettings) btnSaveSettings.innerText = getText(lang, 'btn_save_settings');
    
    const btnChooseFile1 = document.getElementById('btn_choose_file_1');
    if (btnChooseFile1) btnChooseFile1.innerText = getText(lang, 'btn_choose_file');
    
    const editorCoverName = document.getElementById('editor_cover_name');
    if (editorCoverName) {
        const coverInput = document.getElementById('editor_cover');
        if (!coverInput || !coverInput.files || coverInput.files.length === 0) {
            editorCoverName.innerText = getText(lang, 'no_file_chosen');
        }
    }
    
    const btnChooseFile2 = document.getElementById('btn_choose_file_2');
    if (btnChooseFile2) btnChooseFile2.innerText = getText(lang, 'btn_choose_file');
    
    const watermarkName = document.getElementById('settings_watermark_name');
    if (watermarkName) {
        const watermarkInput = document.getElementById('settings_watermark_file');
        if (!watermarkInput || !watermarkInput.files || watermarkInput.files.length === 0) {
            watermarkName.innerText = getText(lang, 'no_file_chosen');
        }
    }
    
    // Clipper translations
    const labelClipperMain = document.getElementById('label_clipper_main');
    if (labelClipperMain) labelClipperMain.innerText = getText(lang, 'label_clipper_main');
    
    const labelClipperDesc = document.getElementById('label_clipper_desc');
    if (labelClipperDesc) labelClipperDesc.innerText = getText(lang, 'label_clipper_desc');
    
    const labelClipperUrl = document.getElementById('label_clipper_url');
    if (labelClipperUrl) labelClipperUrl.innerText = getText(lang, 'label_clipper_url');
    
    const labelClipperStart = document.getElementById('label_clipper_start');
    if (labelClipperStart) labelClipperStart.innerText = getText(lang, 'label_clipper_start');
    
    const labelClipperEnd = document.getElementById('label_clipper_end');
    if (labelClipperEnd) labelClipperEnd.innerText = getText(lang, 'label_clipper_end');
    
    const btnSmartTrim = document.getElementById('btn_smart_trim');
    if (btnSmartTrim) btnSmartTrim.innerText = getText(lang, 'btn_smart_trim');
    
    // Audio Editor translations
    const labelAudioEditorMain = document.getElementById('label_audio_editor_main');
    if (labelAudioEditorMain) labelAudioEditorMain.innerText = getText(lang, 'label_audio_editor_main');
    
    const labelAudioEditorDesc = document.getElementById('label_audio_editor_desc');
    if (labelAudioEditorDesc) labelAudioEditorDesc.innerText = getText(lang, 'label_audio_editor_desc');
    
    const btnAudioEditor = document.getElementById('btn_audio_editor');
    if (btnAudioEditor) btnAudioEditor.innerText = getText(lang, 'btn_audio_editor');
}

function renderProfile() {
    document.getElementById('userName').innerText = userFirstName;
    
    const img = document.getElementById('userAvatar');
    if (userPhotoUrl) {
        img.src = userPhotoUrl;
        img.onerror = function() {
            this.onerror = null;
            this.src = 'assets/avatars/1.jpg';
        };
    } else {
        // Fallback to the default custom avatar
        img.src = `assets/avatars/1.jpg`;
    }
    img.style.display = 'block';
    
    const badge = document.getElementById('userTierBadge');
    badge.innerText = getText(lang, 'tier_' + tier) || tier;
    
    if (tier === 'vip' || tier === 'max' || tier === 'pro' || tier === 'admin') {
        badge.style.background = 'rgba(255, 255, 255, 0.25)';
        badge.style.color = '#ffffff';
        badge.style.borderColor = 'rgba(255, 255, 255, 0.5)';
        badge.style.boxShadow = '0 0 10px rgba(255, 255, 255, 0.2)';
    }

    document.getElementById('userUsed').innerText = used;
    const limitEl = document.getElementById('userLimit');
    if (limitDaily >= 9999) {
        limitEl.innerText = getText(lang, 'stat_unlimited');
        document.getElementById('usageProgressBar').style.width = '100%';
    } else {
        limitEl.innerText = limitDaily;
        const pct = Math.min((used / limitDaily) * 100, 100);
        
        // Slight delay for animation
        setTimeout(() => {
            document.getElementById('usageProgressBar').style.transform = `scaleX(${pct / 100})`;
        }, 100);
    }
    
    // Formatting size
    const sizeEl = document.getElementById('userSizeLimit');
    if (limitSize >= 9999999999) {
        sizeEl.innerText = getText(lang, 'stat_unlimited');
    } else {
        const mb = Math.round(limitSize / (1024 * 1024));
        if (mb >= 1024) {
            sizeEl.innerText = (mb / 1024).toFixed(1) + ' GB';
        } else {
            sizeEl.innerText = mb + ' MB';
        }
    }
    
    // Playlist limit
    const playlistEl = document.getElementById('userPlaylistLimit');
    if (limitPlaylist >= 9999) {
        playlistEl.innerText = getText(lang, 'stat_unlimited');
    } else {
        playlistEl.innerText = limitPlaylist;
    }
    
    // Store Section Active Sub
    if (tier !== 'free' && vipUntilTs > 0) {
        document.getElementById('activeSubInfo').style.display = 'block';
        document.getElementById('activeSubTierName').innerText = getText(lang, 'tier_' + tier) || tier;
        
        const nowTs = Math.floor(Date.now() / 1000);
        const diffDays = Math.max(0, Math.ceil((vipUntilTs - nowTs) / 86400));
        
        const dateObj = new Date(vipUntilTs * 1000);
        const dateStr = dateObj.toLocaleDateString();
        
        document.getElementById('activeSubDate').innerText = dateStr;
        document.getElementById('activeSubDays').innerText = diffDays;
        
        document.getElementById('buyVipBtn').innerText = getText(lang, 'btn_extend_vip');
    }

    // Render badges for current user
    const profile = {
        downloads_count: totalDownloads,
        total_bytes_downloaded: totalBytes,
        badges: userBadges
    };
    renderBadgesGrid('profileBadgesGrid', profile);
}

function renderBadgesGrid(containerId, profile) {
    const badgesGrid = document.getElementById(containerId);
    if (!badgesGrid) return;
    badgesGrid.textContent = '';
    const badgeKeys = Object.keys(ALL_BADGES);
    if (badgeKeys.length > 0) {
        badgeKeys.forEach(b => {
            const badgeDef = ALL_BADGES[b];
            const isUnlocked = (profile.badges || []).includes(b);
            const el = document.createElement('div');
            el.className = 'badge-item';
            el.innerText = badgeDef.icon;
            
            if (!isUnlocked) {
                el.classList.add('locked');
            } else {
                el.classList.add('unlocked');
            }
            
            el.onclick = () => openBadgeModal(b, profile);
            badgesGrid.appendChild(el);
        });
    } else {
        badgesGrid.appendChild(createEl('span', { text: getText(lang, 'no_badges'), style: 'opacity: 0.5; font-size: 0.85rem;' }));
    }
}

// Рядок рейтингу: «#N  ім'я/домен  значення». Усе — через textContent.
function buildRankItem(index, label, value) {
    const li = document.createElement('li');
    li.appendChild(createEl('span', { className: 'rank-index', text: '#' + (index + 1) }));
    li.appendChild(createEl('span', { text: label, style: 'flex: 1; padding-left: 10px;' }));
    li.appendChild(createEl('span', { className: 'rank-value', text: value }));
    return li;
}

function renderLeaderboards() {
    // Render top users
    const usersList = document.getElementById('topUsersList');
    usersList.textContent = '';
    const downloadsWord = getText(lang, 'downloads_count') || 'DL';
    if (topUsersStr) {
        const users = topUsersStr.split(',');
        users.forEach((u, i) => {
            const parts = u.split(':');
            if (parts.length === 3) {
                const li = buildRankItem(i, parts[1], parts[2] + ' ' + downloadsWord);
                // ID із параметра URL перевіряємо, перш ніж підставити його в запит.
                if (/^\d+$/.test(parts[0])) {
                    li.style.cursor = 'pointer';
                    li.addEventListener('click', () => openProfileModal(parts[0]));
                }
                usersList.appendChild(li);
            } else if (parts.length === 2) {
                usersList.appendChild(buildRankItem(i, parts[0], parts[1] + ' ' + downloadsWord));
            }
        });
    } else {
        usersList.appendChild(createEl('li', { text: '-' }));
    }

    // Render top sites
    const sitesList = document.getElementById('topSitesList');
    sitesList.textContent = '';
    if (topSitesStr) {
        const sites = topSitesStr.split(',');
        sites.forEach((s, i) => {
            const parts = s.split(':');
            if (parts.length === 2) {
                sitesList.appendChild(buildRankItem(i, parts[0], parts[1]));
            }
        });
    } else {
        sitesList.appendChild(createEl('li', { text: '-' }));
    }
}

function switchTab(tabId, btnElement) {
    // Update active nav button
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    if (btnElement) btnElement.classList.add('active');
    
    // Update active section
    document.querySelectorAll('.section').forEach(el => el.classList.remove('active'));
    document.getElementById('section-' + tabId).classList.add('active');
    
    // Update title (replace hyphens with underscores for locale keys, e.g. audio-editor -> audio_editor)
    let titleKey = 'title_' + tabId.replace(/-/g, '_');
    document.getElementById('pageTitle').innerText = getText(lang, titleKey);
    
    // Haptic feedback
    try { 
        triggerHaptic('heavy'); 
        setTimeout(() => triggerHaptic('medium'), 30);
    } catch(e){}
    
    if (typeof updateNavVisibility === 'function') {
        updateNavVisibility();
    }
}

function buyVip() {
    triggerHaptic('medium');
    
    tg.showConfirm(getText(lang, 'payment_redirect_alert'), function(confirmed) {
        if (confirmed) {
            const btn = document.getElementById('buyVipBtn');
            btn.innerText = '...';
            
            if (botUsername) {
                // Deep link to bot with /start buy_vip command
                tg.openTelegramLink(`https://t.me/${botUsername}?start=buy_vip`);
                setTimeout(() => tg.close(), 500);
            } else {
                tg.showAlert(getText(lang, 'bot_not_configured'));
            }
        }
    });
}

function toggleSettings() {
    triggerHaptic('medium');
    const navSettings = document.getElementById('nav-settings');
    if (navSettings) {
        switchTab('settings', navSettings);
    }
}

function saveSettings() {
    triggerHaptic('medium');
    const langSel = document.getElementById('settings_language').value;
    const guestQuality = document.getElementById('settings_guest_quality').value;
    const isAnon = document.getElementById('settings_anonymous').checked ? 1 : 0;
    const theme = document.getElementById('settings_theme').value;
    const wp = document.getElementById('settings_watermark_pos').value;
    
    if (!ownedThemes.includes(theme)) {
        tg.sendData(JSON.stringify({action: "buy_theme", theme: theme}));
        tg.close();
        return;
    }
    
    const fileInput = document.getElementById('settings_watermark_file');
    const watermarkUpdated = fileInput.files.length > 0;

    const payload = {
        action: 'save_settings',
        language: langSel,
        default_quality: guestQuality,
        is_anonymous: isAnon,
        theme: theme,
        watermark_position: wp,
        watermark_updated: watermarkUpdated
    };
    
    tg.sendData(JSON.stringify(payload));
}

function timeToSeconds(timeStr) {
    const parts = timeStr.split(':').reverse();
    let seconds = 0;
    for (let i = 0; i < parts.length; i++) {
        seconds += parseInt(parts[i]) * Math.pow(60, i);
    }
    return seconds;
}

function validateTimeFormat(timeStr) {
    return /^(\d{1,2}:)?\d{1,2}:\d{2}$/.test(timeStr);
}

function submitSmartTrim() {
    triggerHaptic('medium');
    const url = document.getElementById('clipper_url').value.trim();
    const startStr = document.getElementById('clipper_start').value.trim();
    const endStr = document.getElementById('clipper_end').value.trim();
    
    if (!url || !startStr || !endStr) {
        tg.showAlert(getText(lang, 'fill_all_fields'));
        return;
    }
    
    if (!validateTimeFormat(startStr) || !validateTimeFormat(endStr)) {
        tg.showAlert(getText(lang, 'error_clipper_format'));
        return;
    }
    
    const startSec = timeToSeconds(startStr);
    const endSec = timeToSeconds(endStr);
    
    if (startSec >= endSec) {
        tg.showAlert(getText(lang, 'error_clipper_times'));
        return;
    }
    
    // Validation passed, send request to bot
    const payload = {
        action: 'smart_trim',
        url: url,
        start: startStr,
        end: endStr,
        start_sec: startSec,
        end_sec: endSec
    };
    
    tg.sendData(JSON.stringify(payload));
}

function submitAudioEditor() {
    triggerHaptic('medium');
    const url = document.getElementById('editor_url').value.trim();
    const title = document.getElementById('editor_title').value.trim();
    const artist = document.getElementById('editor_artist').value.trim();
    const album = document.getElementById('editor_album').value.trim();
    
    if (!url) {
        tg.showAlert(getText(lang, 'enter_track_url'));
        return;
    }
    
    const fileInput = document.getElementById('editor_cover');
    const hasCover = fileInput.files.length > 0;

    const payload = {
        action: 'edit_tags',
        url: url,
        title: title,
        artist: artist,
        album: album,
        has_cover: hasCover
    };
    
    tg.sendData(JSON.stringify(payload));
}

// --- Gamification & Search Logic ---

function setupSearch() {
    const searchInput = document.getElementById('userSearchInput');
    const resultsList = document.getElementById('searchResultsList');
    let debounceTimer;

    if (!searchInput) return;

    searchInput.addEventListener('input', (e) => {
        clearTimeout(debounceTimer);
        const query = e.target.value.trim();
        
        if (query.length < 2) {
            resultsList.style.display = 'none';
            return;
        }

        debounceTimer = setTimeout(async () => {
            try {
                const res = await fetch(`${apiUrl}/search_users?q=${encodeURIComponent(query)}`, {
                    headers: apiHeaders()
                });
                if (!res.ok) throw new Error("Search failed");
                const data = await res.json();

                resultsList.textContent = '';
                if (data.results && data.results.length > 0) {
                    data.results.forEach(user => {
                        const li = document.createElement('li');
                        li.style.cursor = 'pointer';
                        li.addEventListener('click', () => openProfileModal(user.telegram_id));
                        const nameLine = (user.full_name || 'User') + ' (@' + (user.username || 'user') + ')';
                        li.appendChild(createEl('span', { text: nameLine, style: 'flex: 1;' }));
                        li.appendChild(createEl('span', { className: 'rank-value', text: getText(lang, 'tier_' + user.tier) || user.tier }));
                        resultsList.appendChild(li);
                    });
                    resultsList.style.display = 'block';
                } else {
                    showListMessage(resultsList, getText(lang, 'search_not_found'), 'text-align:center; opacity: 0.7;');
                    resultsList.style.display = 'block';
                }
            } catch (err) {
                console.error(err);
                showListMessage(resultsList, getText(lang, 'search_error'), 'text-align:center; opacity: 0.7; color: red;');
                resultsList.style.display = 'block';
            }
        }, 500);
    });
}

async function openProfileModal(userId) {
    document.body.style.overflow = 'hidden';
    triggerHaptic('medium');
    try {
        const res = await fetch(`${apiUrl}/get_profile?id=${encodeURIComponent(userId)}`, {
            headers: apiHeaders()
        });
        if (!res.ok) {
            tg.showAlert(getText(lang, res.status === 404 ? 'profile_hidden' : 'profile_load_error'));
            document.body.style.overflow = '';
            return;
        }
        
        const data = await res.json();
        const profile = data.profile;
        
        document.getElementById('modalUserName').innerText = profile.full_name;
        document.getElementById('modalUserTier').innerText = getText(lang, 'tier_' + profile.tier) || profile.tier;
        document.getElementById('modalDownloads').innerText = profile.downloads_count;
        
        const mb = Math.round(profile.total_bytes_downloaded / (1024 * 1024));
        if (mb >= 1024) {
            document.getElementById('modalTraffic').innerText = (mb / 1024).toFixed(2) + ' GB';
        } else {
            document.getElementById('modalTraffic').innerText = mb + ' MB';
        }
        
        renderBadgesGrid('modalBadgesGrid', profile);
        
        document.getElementById('publicProfileModal').style.display = 'flex';
    } catch (err) {
        console.error(err);
        tg.showAlert(getText(lang, 'profile_load_error'));
        document.body.style.overflow = '';
    }
}

function closeProfileModal() {
    triggerHaptic('light');
    document.getElementById('publicProfileModal').style.display = 'none';
    const badgeModal = document.getElementById('badgeInfoModal');
    if (!badgeModal || badgeModal.style.display === 'none') {
        document.body.style.overflow = '';
    }
}

function openBadgeModal(badgeId, profile) {
    document.body.style.overflow = 'hidden';
    triggerHaptic('light');
    const badgeDef = ALL_BADGES[badgeId];
    if (!badgeDef) return;
    
    document.getElementById('badgeModalIcon').innerText = badgeDef.icon;
    document.getElementById('badgeModalName').innerText = getText(lang, 'badge_' + badgeId + '_name');
    document.getElementById('badgeModalDesc').innerText = getText(lang, 'badge_' + badgeId + '_desc');
    document.getElementById('badgeModalProgressLabel').innerText = getText(lang, 'progress_label') + ':';
    
    const currentProgress = badgeDef.calc(profile);
    const maxProgress = badgeDef.max;
    const pct = Math.min((currentProgress / maxProgress) * 100, 100);
    
    document.getElementById('badgeModalProgressText').innerText = badgeDef.format(currentProgress, maxProgress);
    
    const pb = document.getElementById('badgeModalProgressBar');
    // Allow slight animation delay
    pb.style.transform = `scaleX(0)`;
    setTimeout(() => {
        pb.style.transform = `scaleX(${pct / 100})`;
    }, 50);
    
    const isUnlocked = (profile.badges || []).includes(badgeId);
    if (!isUnlocked) {
        document.getElementById('badgeModalIcon').style.filter = 'grayscale(100%)';
        document.getElementById('badgeModalIcon').style.opacity = '0.5';
    } else {
        document.getElementById('badgeModalIcon').style.filter = 'none';
        document.getElementById('badgeModalIcon').style.opacity = '1';
    }
    
    document.getElementById('badgeInfoModal').style.display = 'flex';
}

function closeBadgeModal() {
    triggerHaptic('light');
    document.getElementById('badgeInfoModal').style.display = 'none';
    const publicModal = document.getElementById('publicProfileModal');
    if (!publicModal || publicModal.style.display === 'none') {
        document.body.style.overflow = '';
    }
}

function initCustomSelects() {
    const selects = document.querySelectorAll('select.glass-input');
    selects.forEach(select => {
        // Create wrapper
        const wrapper = document.createElement('div');
        wrapper.className = 'custom-select-wrapper';
        select.parentNode.insertBefore(wrapper, select);
        wrapper.appendChild(select);
        
        // Hide original select
        select.style.display = 'none';
        
        // Create trigger
        const trigger = document.createElement('div');
        trigger.className = 'custom-select-trigger glass-input';
        
        // Find selected option
        let selectedOption = select.options[select.selectedIndex];
        if (!selectedOption && select.options.length > 0) {
            selectedOption = select.options[0];
        }
        trigger.appendChild(createEl('span', { text: selectedOption ? selectedOption.text : '' }));
        trigger.appendChild(createEl('div', { className: 'arrow' }));
        wrapper.appendChild(trigger);
        
        // Create options container
        const optionsContainer = document.createElement('div');
        optionsContainer.className = 'custom-select-options glass';
        
        Array.from(select.options).forEach(option => {
            const optDiv = document.createElement('div');
            optDiv.className = 'custom-select-option';
            optDiv.dataset.value = option.value;
            optDiv.textContent = option.text;
            
            if (option.selected) optDiv.classList.add('selected');
            
            optDiv.addEventListener('click', function(e) {
                // Update original select
                select.value = this.dataset.value;
                // Dispatch change event
                select.dispatchEvent(new Event('change'));
                
                // Update trigger text
                trigger.querySelector('span').textContent = this.textContent;
                
                // Update selected class
                optionsContainer.querySelectorAll('.custom-select-option').forEach(el => el.classList.remove('selected'));
                this.classList.add('selected');
                
                // Close dropdown
                wrapper.classList.remove('open');
                triggerHaptic('light');
            });
            
            optionsContainer.appendChild(optDiv);
        });
        
        wrapper.appendChild(optionsContainer);
        
        // Toggle dropdown
        trigger.addEventListener('click', function(e) {
            e.stopPropagation();
            
            // Close other open selects
            document.querySelectorAll('.custom-select-wrapper').forEach(w => {
                if (w !== wrapper) {
                    w.classList.remove('open');
                    w.style.zIndex = '1';
                }
            });
            
            wrapper.classList.toggle('open');
            wrapper.style.zIndex = wrapper.classList.contains('open') ? '99' : '1';
            triggerHaptic('light');
        });
    });
    
    // Close on click outside
    document.addEventListener('click', function() {
        document.querySelectorAll('.custom-select-wrapper').forEach(w => {
            w.classList.remove('open');
            w.style.zIndex = '1';
        });
    });
}

function updateNavVisibility() {
    const tabs = ['profile', 'leaderboard', 'store', 'clipper', 'audio-editor', 'settings'];
    let currentIndex = 0;
    document.querySelectorAll('.section').forEach((sec, idx) => {
        if (sec.classList.contains('active')) currentIndex = idx;
    });
    
    let startIdx = Math.max(0, currentIndex - 1);
    let endIdx = startIdx + 2;
    const navItems = document.querySelectorAll('.nav-item');
    if (endIdx >= navItems.length) {
        endIdx = navItems.length - 1;
        startIdx = Math.max(0, endIdx - 2);
    }
    
    navItems.forEach((item, idx) => {
        if (idx >= startIdx && idx <= endIdx) {
            item.style.display = 'flex';
        } else {
            item.style.display = 'none';
        }
    });
}
