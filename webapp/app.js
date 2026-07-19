const tg = window.Telegram.WebApp;

let hapticEnabled = localStorage.getItem('hapticEnabled') !== 'false';

function triggerHaptic(style) {
    if (hapticEnabled) {
        try { tg.HapticFeedback.impactOccurred(style); } catch(e){}
    }
}

// Extract URL parameters
const urlParams = new URLSearchParams(window.location.search);
const lang = urlParams.get('l') || 'uk';
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

const BADGE_ICONS = {
    'first_blood': '🩸',
    'heavy_lifter': '🏋️‍♂️',
    'night_owl': '🦉'
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
            localStorage.setItem('hapticEnabled', hapticEnabled);
            triggerHaptic('medium');
        });
    }

    // Pre-fill settings form
    const selLang = document.getElementById('settings_language');
    if (selLang) selLang.value = lang;

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
                    btn.innerText = "Купити за 50 ⭐️";
                } else {
                    btn.innerText = getText(lang, 'btn_save_settings') || "Save settings";
                }
            }
        });
    }

    const selWatermarkPos = document.getElementById('settings_watermark_pos');
    if (selWatermarkPos) selWatermarkPos.value = currentWatermarkPos;
    
    // Interactive spotlight and prism effect
    const updateCursorPos = (e) => {
        let clientX = e.clientX;
        let clientY = e.clientY;
        if (e.touches && e.touches.length > 0) {
            clientX = e.touches[0].clientX;
            clientY = e.touches[0].clientY;
        }
        
        document.querySelectorAll('.glass').forEach(card => {
            const rect = card.getBoundingClientRect();
            const x = clientX - rect.left;
            const y = clientY - rect.top;
            
            const rotX = -((y / rect.height) - 0.5) * 10;
            const rotY = ((x / rect.width) - 0.5) * 10;
            
            card.style.setProperty('--mouse-x', `${x}px`);
            card.style.setProperty('--mouse-y', `${y}px`);
            card.style.setProperty('--rot-x', `${rotX}deg`);
            card.style.setProperty('--rot-y', `${rotY}deg`);
        });
    };

    document.body.addEventListener('mousemove', updateCursorPos);
    document.body.addEventListener('touchmove', updateCursorPos);
    
    // Add touch class for mobile so the effect is visible while touching
    document.querySelectorAll('.glass').forEach(card => {
        card.addEventListener('touchstart', (e) => {
            updateCursorPos(e);
            card.classList.add('touching');
            if (card.classList.contains('card')) {
                try { 
                    triggerHaptic('heavy'); 
                    setTimeout(() => triggerHaptic('heavy'), 20);
                    setTimeout(() => triggerHaptic('heavy'), 40);
                } catch(e){}
            }
        }, {passive: true});
        card.addEventListener('touchend', () => {
            card.classList.remove('touching');
            if (card.classList.contains('card')) {
                try { 
                    triggerHaptic('heavy'); 
                } catch(e){}
            }
        });
        card.addEventListener('touchcancel', () => {
            card.classList.remove('touching');
        });
    });

    // Swipe navigation logic
    let touchStartX = 0;
    let touchStartY = 0;
    let lastSwipeVibrateX = 0;
    const swipeThreshold = 60; // minimum distance in px
    
    document.body.addEventListener('touchstart', (e) => {
        touchStartX = e.changedTouches[0].screenX;
        touchStartY = e.changedTouches[0].screenY;
        lastSwipeVibrateX = 0;
    }, {passive: true});
    
    document.body.addEventListener('touchmove', (e) => {
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

    document.body.addEventListener('touchend', (e) => {
        const touchEndX = e.changedTouches[0].screenX;
        const touchEndY = e.changedTouches[0].screenY;
        
        const deltaX = touchStartX - touchEndX;
        const deltaY = Math.abs(touchStartY - touchEndY);
        
        // Prevent swipe if vertical scrolling was dominant
        if (Math.abs(deltaX) > deltaY && Math.abs(deltaX) > swipeThreshold) {
            const tabs = ['profile', 'leaderboard', 'store', 'clipper', 'settings'];
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
});

function applyTranslations() {
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
    
    const tabSettingsEl = document.getElementById('tab_settings');
    if (tabSettingsEl) tabSettingsEl.innerText = getText(lang, 'title_settings');
    
    const tabClipperEl = document.getElementById('tab_clipper');
    if (tabClipperEl) tabClipperEl.innerText = getText(lang, 'title_clipper');
    
    // Settings translations
    const labelSettingsMain = document.getElementById('label_settings_main');
    if (labelSettingsMain) labelSettingsMain.innerText = getText(lang, 'label_settings_main');
    
    const labelLanguage = document.getElementById('label_language');
    if (labelLanguage) labelLanguage.innerText = getText(lang, 'label_language');
    
    const labelGuestQuality = document.getElementById('label_guest_quality');
    if (labelGuestQuality) labelGuestQuality.innerText = getText(lang, 'label_guest_quality');
    
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
}

function renderLeaderboards() {
    // Render top users
    const usersList = document.getElementById('topUsersList');
    if (topUsersStr) {
        const users = topUsersStr.split(',');
        users.forEach((u, i) => {
            const parts = u.split(':');
            if (parts.length === 3) {
                const li = document.createElement('li');
                li.style.cursor = 'pointer';
                li.onclick = () => openProfileModal(parts[0]);
                li.innerHTML = `<span class="rank-index">#${i+1}</span><span style="flex: 1; padding-left: 10px;">${parts[1]}</span><span class="rank-value">${parts[2]} ${getText(lang, 'downloads_count') || 'DL'}</span>`;
                usersList.appendChild(li);
            } else if (parts.length === 2) {
                const li = document.createElement('li');
                li.innerHTML = `<span class="rank-index">#${i+1}</span><span style="flex: 1; padding-left: 10px;">${parts[0]}</span><span class="rank-value">${parts[1]} ${getText(lang, 'downloads_count') || 'DL'}</span>`;
                usersList.appendChild(li);
            }
        });
    } else {
        usersList.innerHTML = '<li>-</li>';
    }
    
    // Render top sites
    const sitesList = document.getElementById('topSitesList');
    if (topSitesStr) {
        const sites = topSitesStr.split(',');
        sites.forEach((s, i) => {
            const parts = s.split(':');
            if (parts.length === 2) {
                const li = document.createElement('li');
                li.innerHTML = `<span class="rank-index">#${i+1}</span><span style="flex: 1; padding-left: 10px;">${parts[0]}</span><span class="rank-value">${parts[1]}</span>`;
                sitesList.appendChild(li);
            }
        });
    } else {
        sitesList.innerHTML = '<li>-</li>';
    }
}

function switchTab(tabId, btnElement) {
    // Update active nav button
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    if (btnElement) btnElement.classList.add('active');
    
    // Update active section
    document.querySelectorAll('.section').forEach(el => el.classList.remove('active'));
    document.getElementById('section-' + tabId).classList.add('active');
    
    // Update title
    document.getElementById('pageTitle').innerText = getText(lang, 'title_' + tabId);
    
    // Haptic feedback
    try { 
        triggerHaptic('heavy'); 
        setTimeout(() => triggerHaptic('medium'), 30);
    } catch(e){}
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
                tg.showAlert("Bot username not configured!");
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
        tg.showAlert("Будь ласка, заповніть всі поля.");
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
        tg.showAlert("Будь ласка, введіть посилання на трек.");
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
                const res = await fetch(`${apiUrl}/search_users?q=${encodeURIComponent(query)}&initData=${encodeURIComponent(tg.initData || '')}`);
                if (!res.ok) throw new Error("Search failed");
                const data = await res.json();
                
                resultsList.innerHTML = '';
                if (data.results && data.results.length > 0) {
                    data.results.forEach(user => {
                        const li = document.createElement('li');
                        li.style.cursor = 'pointer';
                        li.onclick = () => openProfileModal(user.telegram_id);
                        li.innerHTML = `<span style="flex: 1;">${user.full_name} (@${user.username || 'user'})</span><span class="rank-value">${user.tier}</span>`;
                        resultsList.appendChild(li);
                    });
                    resultsList.style.display = 'block';
                } else {
                    resultsList.innerHTML = '<li style="text-align:center; opacity: 0.7;">Не знайдено</li>';
                    resultsList.style.display = 'block';
                }
            } catch (err) {
                console.error(err);
                resultsList.innerHTML = '<li style="text-align:center; opacity: 0.7; color: red;">Помилка завантаження</li>';
                resultsList.style.display = 'block';
            }
        }, 500);
    });
}

async function openProfileModal(userId) {
    triggerHaptic('medium');
    try {
        const res = await fetch(`${apiUrl}/get_profile?id=${userId}&initData=${encodeURIComponent(tg.initData || '')}`);
        if (!res.ok) {
            let errorMsg = "Профіль приховано або не знайдено";
            try {
                const data = await res.json();
                if (data.error) errorMsg = data.error;
            } catch (e) {}
            tg.showAlert(errorMsg);
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
        
        const badgesGrid = document.getElementById('modalBadgesGrid');
        badgesGrid.innerHTML = '';
        if (profile.badges && profile.badges.length > 0) {
            profile.badges.forEach(b => {
                const icon = BADGE_ICONS[b] || '🏆';
                const el = document.createElement('div');
                el.style.fontSize = '2rem';
                el.style.textAlign = 'center';
                el.title = b;
                el.innerText = icon;
                badgesGrid.appendChild(el);
            });
        } else {
            badgesGrid.innerHTML = '<span style="opacity: 0.5; font-size: 0.85rem;">Немає бейджів</span>';
        }
        
        document.getElementById('publicProfileModal').style.display = 'block';
    } catch (err) {
        console.error(err);
        tg.showAlert("Помилка завантаження профілю.");
    }
}

function closeProfileModal() {
    triggerHaptic('light');
    document.getElementById('publicProfileModal').style.display = 'none';
}
