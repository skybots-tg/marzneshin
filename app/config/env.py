"""Backward-compatible shim.

All settings are now managed by ``app.core.settings.Settings``.
This module re-exports every name that the rest of the codebase expects
so that existing ``from app.config.env import X`` statements keep working.
"""

from app.core.settings import AuthAlgorithm, settings as _s

# Database
SQLALCHEMY_DATABASE_URL = _s.db.database_url
SQLALCHEMY_CONNECTION_POOL_SIZE = _s.db.connection_pool_size
SQLALCHEMY_CONNECTION_MAX_OVERFLOW = _s.db.connection_max_overflow
SQLALCHEMY_POOL_TIMEOUT = _s.db.pool_timeout
SQLALCHEMY_POOL_RECYCLE = _s.db.pool_recycle
SQLALCHEMY_STATEMENT_TIMEOUT = _s.db.statement_timeout
SQLALCHEMY_CONNECT_TIMEOUT = _s.db.connect_timeout

# Uvicorn
UVICORN_HOST = _s.uvicorn.host
UVICORN_PORT = _s.uvicorn.port
UVICORN_UDS = _s.uvicorn.uds
UVICORN_SSL_CERTFILE = _s.uvicorn.ssl_certfile
UVICORN_SSL_KEYFILE = _s.uvicorn.ssl_keyfile
UVICORN_TIMEOUT_KEEP_ALIVE = _s.uvicorn.timeout_keep_alive
REQUEST_TIMEOUT = _s.request_timeout

# App flags
DEBUG = _s.debug
DOCS = _s.docs
DASHBOARD_PATH = _s.dashboard_path
VITE_BASE_API = _s.vite_base_api

# Subscription
SUBSCRIPTION_URL_PREFIX = _s.subscription_url_prefix
SUBSCRIPTION_PAGE_TEMPLATE = _s.subscription_templates.subscription_page_template
SINGBOX_SUBSCRIPTION_TEMPLATE = _s.subscription_templates.singbox_subscription_template
XRAY_SUBSCRIPTION_TEMPLATE = _s.subscription_templates.xray_subscription_template
CLASH_SUBSCRIPTION_TEMPLATE = _s.subscription_templates.clash_subscription_template

# Telegram
TELEGRAM_API_TOKEN = _s.telegram.api_token
TELEGRAM_ADMIN_ID = _s.telegram.admin_id
TELEGRAM_PROXY_URL = _s.telegram.proxy_url
TELEGRAM_LOGGER_CHANNEL_ID = _s.telegram.logger_channel_id

# Webhook
WEBHOOK_ADDRESS = _s.webhook.address
WEBHOOK_SECRET = _s.webhook.secret

# Auth
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = _s.jwt_access_token_expire_minutes
AUTH_GENERATION_ALGORITHM = _s.auth_generation_algorithm

# Templates
CUSTOM_TEMPLATES_DIRECTORY = _s.custom_templates_directory
HOME_PAGE_TEMPLATE = _s.home_page_template

# Device
ENFORCE_DEVICE_LIMITS_ON_PROXY = _s.enforce_device_limits_on_proxy

# Notifications
RECURRENT_NOTIFICATIONS_TIMEOUT = _s.notification.recurrent_notifications_timeout
NUMBER_OF_RECURRENT_NOTIFICATIONS = _s.notification.number_of_recurrent_notifications
NOTIFY_REACHED_USAGE_PERCENT = _s.notification.notify_reached_usage_percent
NOTIFY_DAYS_LEFT = _s.notification.notify_days_left
NODE_UNHEALTHY_ALERT_COOLDOWN = _s.notification.node_unhealthy_alert_cooldown
DISABLE_RECORDING_NODE_USAGE = _s.notification.disable_recording_node_usage

# Tasks
TASKS_RECORD_USER_USAGES_INTERVAL = _s.tasks.record_user_usages_interval
TASKS_REVIEW_USERS_INTERVAL = _s.tasks.review_users_interval
TASKS_EXPIRE_DAYS_REACHED_INTERVAL = _s.tasks.expire_days_reached_interval
TASKS_RESET_USER_DATA_USAGE = _s.tasks.reset_user_data_usage
