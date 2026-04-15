from enum import Enum
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthAlgorithm(Enum):
    PLAIN = "plain"
    XXH128 = "xxh128"


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SQLALCHEMY_")

    database_url: str = Field(default="sqlite:///db.sqlite3")
    connection_pool_size: int = 20
    connection_max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 1800
    statement_timeout: int = 25
    connect_timeout: int = 10


class UvicornSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UVICORN_")

    host: str = "0.0.0.0"
    port: int = 8000
    uds: Optional[str] = None
    ssl_certfile: Optional[str] = None
    ssl_keyfile: Optional[str] = None
    timeout_keep_alive: int = 5


class TelegramSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")

    api_token: str = ""
    admin_id: str = ""
    proxy_url: str = ""
    logger_channel_id: int = 0

    def get_admin_ids(self) -> list[int]:
        raw = self.admin_id.strip().strip("[]")
        if not raw:
            return []
        return [
            int(i)
            for i in filter(
                str.isdigit, (s.strip() for s in raw.split(","))
            )
        ]


class WebhookSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WEBHOOK_")

    address: Optional[str] = None
    secret: Optional[str] = None


class TasksSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TASKS_")

    record_user_usages_interval: int = 30
    review_users_interval: int = 30
    expire_days_reached_interval: int = 30
    reset_user_data_usage: int = 3600
    usage_retention_days: int = 30


class NotificationSettings(BaseSettings):
    recurrent_notifications_timeout: int = Field(
        default=180, alias="RECURRENT_NOTIFICATIONS_TIMEOUT"
    )
    number_of_recurrent_notifications: int = Field(
        default=3, alias="NUMBER_OF_RECURRENT_NOTIFICATIONS"
    )
    notify_reached_usage_percent: int = Field(
        default=80, alias="NOTIFY_REACHED_USAGE_PERCENT"
    )
    notify_days_left: int = Field(default=3, alias="NOTIFY_DAYS_LEFT")
    node_unhealthy_alert_cooldown: int = Field(
        default=10800, alias="NODE_UNHEALTHY_ALERT_COOLDOWN"
    )
    disable_recording_node_usage: bool = Field(
        default=False, alias="DISABLE_RECORDING_NODE_USAGE"
    )

    model_config = SettingsConfigDict(populate_by_name=True)


class SubscriptionTemplateSettings(BaseSettings):
    singbox_subscription_template: Optional[str] = Field(
        default=None, alias="SINGBOX_SUBSCRIPTION_TEMPLATE"
    )
    xray_subscription_template: Optional[str] = Field(
        default=None, alias="XRAY_SUBSCRIPTION_TEMPLATE"
    )
    clash_subscription_template: Optional[str] = Field(
        default=None, alias="CLASH_SUBSCRIPTION_TEMPLATE"
    )
    subscription_page_template: str = Field(
        default="subscription/index.html",
        alias="SUBSCRIPTION_PAGE_TEMPLATE",
    )

    model_config = SettingsConfigDict(populate_by_name=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    debug: bool = Field(default=False, alias="DEBUG")
    docs: bool = Field(default=False, alias="DOCS")

    dashboard_path: str = Field(
        default="/dashboard/", alias="DASHBOARD_PATH"
    )
    subscription_url_prefix: str = Field(
        default="", alias="SUBSCRIPTION_URL_PREFIX"
    )

    jwt_access_token_expire_minutes: int = Field(
        default=1440, alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    auth_generation_algorithm: AuthAlgorithm = Field(
        default=AuthAlgorithm.XXH128, alias="AUTH_GENERATION_ALGORITHM"
    )

    custom_templates_directory: Optional[str] = Field(
        default=None, alias="CUSTOM_TEMPLATES_DIRECTORY"
    )
    home_page_template: str = Field(
        default="home/index.html", alias="HOME_PAGE_TEMPLATE"
    )

    request_timeout: int = Field(default=30, alias="REQUEST_TIMEOUT")

    enforce_device_limits_on_proxy: bool = Field(
        default=True, alias="ENFORCE_DEVICE_LIMITS_ON_PROXY"
    )

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    uvicorn: UvicornSettings = Field(default_factory=UvicornSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    webhook: WebhookSettings = Field(default_factory=WebhookSettings)
    tasks: TasksSettings = Field(default_factory=TasksSettings)
    notification: NotificationSettings = Field(
        default_factory=NotificationSettings
    )
    subscription_templates: SubscriptionTemplateSettings = Field(
        default_factory=SubscriptionTemplateSettings
    )

    @field_validator("subscription_url_prefix", mode="after")
    @classmethod
    def strip_prefix_slashes(cls, v: str) -> str:
        return v.strip("/")

    @property
    def vite_base_api(self) -> str:
        from decouple import config as decouple_config

        raw = decouple_config("VITE_BASE_API", default="/api/")
        if self.debug and raw == "/api/":
            return f"http://127.0.0.1:{self.uvicorn.port}/api/"
        return raw


settings = Settings()
