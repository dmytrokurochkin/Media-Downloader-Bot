const locales = {
    'uk': {
        'title_profile': 'Мій Профіль',
        'title_leaderboard': 'Рейтинги',
        'title_store': 'VIP Магазин',
        'tier_free': 'Безкоштовний',
        'tier_vip': 'VIP Доступ',
        'tier_admin': 'Адміністратор',
        'stat_downloads': 'Завантажень сьогодні:',
        'stat_unlimited': 'Безліміт',
        'buy_vip_btn': 'Придбати VIP (Stars)',
        'top_users': 'Топ Користувачів',
        'top_sites': 'Популярні Сайти',
        'downloads_count': 'завантажень',
        'vip_benefits': 'Переваги VIP',
        'vip_desc_1': '🚀 Безлімітні завантаження',
        'vip_desc_2': '📁 Підтримка файлів до 2 ГБ',
        'vip_desc_3': '⚡ Максимальна швидкість',
        'vip_desc_4': '🎶 Висока якість аудіо',
        'buy_success_msg': 'Відкриття оплати в Telegram...',
        'payment_redirect_alert': 'Для безпечної оплати через Telegram Stars, вас буде перенаправлено в чат з ботом. Бажаєте продовжити?',
        'limit_size': 'Макс. розмір:',
        'limit_playlist': 'Плейлисти:',
        'stat_unlimited': 'Безліміт',
        'stat_daily_limit': 'Денний ліміт:'
    },
    'en': {
        'title_profile': 'My Profile',
        'title_leaderboard': 'Leaderboard',
        'title_store': 'VIP Store',
        'tier_free': 'Free Tier',
        'tier_vip': 'VIP Access',
        'tier_admin': 'Administrator',
        'stat_downloads': 'Downloads today:',
        'stat_unlimited': 'Unlimited',
        'buy_vip_btn': 'Buy VIP (Stars)',
        'top_users': 'Top Users',
        'top_sites': 'Popular Sites',
        'downloads_count': 'downloads',
        'vip_benefits': 'VIP Benefits',
        'vip_desc_1': '🚀 Unlimited downloads',
        'vip_desc_2': '📁 File support up to 2 GB',
        'vip_desc_3': '⚡ Maximum speed',
        'vip_desc_4': '🎶 High quality audio',
        'buy_success_msg': 'Opening payment in Telegram...',
        'payment_redirect_alert': 'For secure payment via Telegram Stars, you will be redirected to the bot chat. Continue?',
        'limit_size': 'Max Size:',
        'limit_playlist': 'Playlists:',
        'stat_unlimited': 'Unlimited',
        'stat_daily_limit': 'Daily Limit:'
    },
    'ru': {
        'title_profile': 'Мой Профиль',
        'title_leaderboard': 'Рейтинги',
        'title_store': 'VIP Магазин',
        'tier_free': 'Бесплатный',
        'tier_vip': 'VIP Доступ',
        'tier_admin': 'Администратор',
        'stat_downloads': 'Скачиваний сегодня:',
        'stat_unlimited': 'Безлимит',
        'buy_vip_btn': 'Купить VIP (Stars)',
        'top_users': 'Топ Пользователей',
        'top_sites': 'Популярные Сайты',
        'downloads_count': 'скачиваний',
        'vip_benefits': 'Преимущества VIP',
        'vip_desc_1': '🚀 Безлимитные загрузки',
        'vip_desc_2': '📁 Поддержка файлов до 2 ГБ',
        'vip_desc_3': '⚡ Максимальная скорость',
        'vip_desc_4': '🎶 Высокое качество аудио',
        'buy_success_msg': 'Открытие оплаты в Telegram...',
        'payment_redirect_alert': 'Для безопасной оплаты через Telegram Stars, вы будете перенаправлены в чат с ботом. Продолжить?',
        'limit_size': 'Макс. размер:',
        'limit_playlist': 'Плейлисты:',
        'stat_unlimited': 'Безлимит',
        'stat_daily_limit': 'Дневной лимит:'
    }
};

function getText(lang, key) {
    if (!locales[lang]) {
        lang = 'en'; // default
    }
    return locales[lang][key] || locales['en'][key] || key;
}
