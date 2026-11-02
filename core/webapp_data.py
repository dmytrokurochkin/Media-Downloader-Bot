"""
Схеми даних, які Mini App надсилає боту через `Telegram.WebApp.sendData()`.

Ці дані НЕ довірені: з увімкненим інспектором WebView (Telegram Desktop тощо)
будь-хто може викликати sendData з довільним JSON. Раніше хендлер брав поля як є:
невідома якість відео давала Free-користувачу «best», рядок замість числа валив
Smart Trim з TypeError, а від'ємна тривалість обходила ліміт у 30 секунд.
Тут кожне поле має тип, межі та allowlist значень; усе інше — ValidationError.
"""
import re
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

LANGUAGES = ("uk", "en", "pl")
GUEST_QUALITIES = ("best", "1080p", "720p", "480p", "360p", "audio")
WATERMARK_POSITIONS = ("top_left", "top_right", "bottom_left", "bottom_right")
THEMES = ("standard", "neon", "retro")
PAID_THEMES = ("neon", "retro")

# Межі для Smart Trim: позиція в межах доби, і мінімальна тривалість фрагмента.
MAX_TRIM_POSITION_SEC = 24 * 60 * 60
MIN_TRIM_DURATION_SEC = 1

_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


class _Payload(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


def _validate_url(value: str) -> str:
    # Лише http(s) і без пробілів: рядок, що починається з `-`, не пройде і не стане
    # опцією для gallery-dl/spotdl. Приватні адреси відсікає net_guard при завантаженні.
    if not _URL_RE.match(value):
        raise ValueError("Посилання має починатися з http:// або https://")
    return value


class SaveSettings(_Payload):
    action: Literal["save_settings"]
    language: Optional[Literal["uk", "en", "pl"]] = None
    default_quality: Optional[Literal["best", "1080p", "720p", "480p", "360p", "audio"]] = None
    is_anonymous: bool = False
    theme: Optional[Literal["standard", "neon", "retro"]] = None
    watermark_position: Optional[Literal["top_left", "top_right", "bottom_left", "bottom_right"]] = None
    watermark_updated: bool = False


class BuyTheme(_Payload):
    action: Literal["buy_theme"]
    theme: Literal["neon", "retro"]


class SmartTrim(_Payload):
    action: Literal["smart_trim"]
    url: str = Field(max_length=2048)
    start_sec: int = Field(ge=0, le=MAX_TRIM_POSITION_SEC)
    end_sec: int = Field(ge=MIN_TRIM_DURATION_SEC, le=MAX_TRIM_POSITION_SEC)

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        return _validate_url(value)

    @model_validator(mode="after")
    def _end_after_start(self):
        if self.end_sec - self.start_sec < MIN_TRIM_DURATION_SEC:
            raise ValueError("Кінець фрагмента має бути пізніше за початок")
        return self

    @property
    def duration(self) -> int:
        return self.end_sec - self.start_sec


class EditTags(_Payload):
    action: Literal["edit_tags"]
    url: str = Field(max_length=2048)
    title: str = Field(default="", max_length=200)
    artist: str = Field(default="", max_length=200)
    album: str = Field(default="", max_length=200)
    has_cover: bool = False

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        return _validate_url(value)


WebAppPayload = Annotated[
    Union[SaveSettings, BuyTheme, SmartTrim, EditTags],
    Field(discriminator="action"),
]

_payload_adapter = TypeAdapter(WebAppPayload)


def parse_webapp_payload(raw: str):
    """Розбирає JSON із web_app_data у відповідну модель або кидає pydantic.ValidationError."""
    return _payload_adapter.validate_json(raw)


def normalize_guest_quality(quality: Optional[str], tier: str) -> str:
    """Якість YouTube для гостьового режиму з урахуванням тарифу.

    Невідоме значення (стара БД, підроблені дані) раніше падало в гілку «best»,
    тобто Free отримував максимальну якість. Тепер воно стає дефолтом тарифу.
    """
    if quality not in GUEST_QUALITIES:
        quality = "best"
    if tier == "free" and quality in ("best", "1080p"):
        return "720p"
    if tier == "pro" and quality == "best":
        return "1080p"
    return quality
