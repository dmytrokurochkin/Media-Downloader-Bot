const tg = window.Telegram.WebApp;

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
    
    // Tell Telegram app is ready
    tg.ready();
    
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
            card.style.setProperty('--mouse-x', `${x}px`);
            card.style.setProperty('--mouse-y', `${y}px`);
        });
    };

    document.body.addEventListener('mousemove', updateCursorPos);
    document.body.addEventListener('touchmove', updateCursorPos);
    
    // Add touch class for mobile so the effect is visible while touching
    document.querySelectorAll('.glass').forEach(card => {
        card.addEventListener('touchstart', (e) => {
            updateCursorPos(e);
            card.classList.add('touching');
        });
        card.addEventListener('touchend', () => card.classList.remove('touching'));
        card.addEventListener('touchcancel', () => card.classList.remove('touching'));
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
            if (parts.length === 2) {
                const li = document.createElement('li');
                li.innerHTML = `<span class="rank-index">#${i+1}</span><span style="flex: 1; padding-left: 10px;">${parts[0]}</span><span class="rank-value">${parts[1]} ${getText(lang, 'downloads_count')}</span>`;
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
    btnElement.classList.add('active');
    
    // Update active section
    document.querySelectorAll('.section').forEach(el => el.classList.remove('active'));
    document.getElementById('section-' + tabId).classList.add('active');
    
    // Update title
    document.getElementById('pageTitle').innerText = getText(lang, 'title_' + tabId);
    
    // Haptic feedback
    tg.HapticFeedback.selectionChanged();
}

function buyVip() {
    tg.HapticFeedback.impactOccurred('medium');
    
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
