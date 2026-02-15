import re
from collections import defaultdict

from fastapi import APIRouter, Query
from fastapi import Header, HTTPException, Path, Request, Response
from starlette.responses import HTMLResponse

from app.db import crud
from app.db.crud import get_hosts_for_user, get_subscription_settings_cached, get_node_coefficients
from app.dependencies import DBDep, SubUserDep, StartDateDep, EndDateDep
from app.models.settings import SubscriptionSettings
from app.models.system import TrafficUsageSeries
from app.models.user import UserResponse
from app.utils.share import (
    encode_title,
    generate_subscription,
    generate_subscription_template,
)
from app.utils.crypto import encrypt_content

router = APIRouter(prefix="/sub", tags=["Subscription"])


config_mimetype = defaultdict(
    lambda: "text/plain",
    {
        "links": "text/plain",
        "base64-links": "text/plain",
        "sing-box": "application/json",
        "xray": "application/json",
        "clash": "text/yaml",
        "clash-meta": "text/yaml",
        "template": "text/html",
        "block": "text/plain",
    },
)


def get_subscription_user_info(user: UserResponse) -> dict:
    return {
        "upload": 0,
        "download": user.used_traffic,
        "total": user.data_limit or 0,
        "expire": (
            int(user.expire_date.timestamp())
            if user.expire_strategy == "fixed_date"
            else 0
        ),
    }


@router.get("/{username}/{key}")
def user_subscription(
    db_user: SubUserDep,
    request: Request,
    db: DBDep,
    user_agent: str = Header(default=""),
):
    """
    Subscription link, result format depends on subscription settings
    """

    user: UserResponse = UserResponse.model_validate(db_user)

    # Update subscription info (non-blocking, uses separate connection)
    crud.update_user_sub(db, db_user, user_agent)

    # Load settings from cache (60s TTL) and hosts in optimized query
    subscription_settings = SubscriptionSettings.model_validate(
        get_subscription_settings_cached(db)
    )
    
    # Pre-load hosts ONCE for the entire request (major optimization!)
    service_ids = [s.id for s in db_user.services]
    hosts = get_hosts_for_user(db, db_user.id, service_ids=service_ids)

    # Pre-load node coefficients for traffic limit labels
    node_coefficients = get_node_coefficients(db) if user.data_limit_reached else None

    # When only data_limit_reached (not expired/disabled), don't use placeholder —
    # show real configs with [кончился трафик] labels instead
    only_data_limit = (
        user.data_limit_reached
        and user.enabled
        and not user.expired
    )
    use_placeholder = (
        not user.is_active
        and not only_data_limit
        and subscription_settings.placeholder_if_disabled
    )

    if (
        subscription_settings.template_on_acceptance
        and "text/html" in request.headers.get("Accept", [])
    ):
        return HTMLResponse(
            generate_subscription_template(
                db_user, subscription_settings, hosts=hosts,
                data_limit_reached=user.data_limit_reached,
                node_coefficients=node_coefficients,
            )
        )

    response_headers = {
        "content-disposition": f'attachment; filename="{user.username}"',
        "profile-web-page-url": str(request.url),
        "support-url": subscription_settings.support_link,
        "profile-title": encode_title(subscription_settings.profile_title),
        "profile-update-interval": str(subscription_settings.update_interval),
        "subscription-userinfo": "; ".join(
            f"{key}={val}"
            for key, val in get_subscription_user_info(user).items()
        ),
    }

    for rule in subscription_settings.rules:
        if re.match(rule.pattern, user_agent):
            if rule.result.value == "template":
                return HTMLResponse(
                    generate_subscription_template(
                        db_user, subscription_settings, hosts=hosts,
                        data_limit_reached=user.data_limit_reached,
                        node_coefficients=node_coefficients,
                    )
                )
            elif rule.result.value == "block":
                raise HTTPException(404)
            elif rule.result.value == "base64-links":
                b64 = True
                config_format = "links"
            else:
                b64 = False
                config_format = rule.result.value

            conf = generate_subscription(
                user=db_user,
                config_format=config_format,
                as_base64=b64,
                use_placeholder=use_placeholder,
                placeholder_remark=subscription_settings.placeholder_remark,
                shuffle=subscription_settings.shuffle_configs,
                hosts=hosts,
                data_limit_reached=user.data_limit_reached,
                node_coefficients=node_coefficients,
            )
            return Response(
                content=conf,
                media_type=config_mimetype[rule.result],
                headers=response_headers,
            )


@router.get("/{username}/{key}/info", response_model=UserResponse)
def user_subscription_info(db_user: SubUserDep):
    return db_user


@router.get("/{username}/{key}/usage", response_model=TrafficUsageSeries)
def user_get_usage(
    db_user: SubUserDep,
    db: DBDep,
    start_date: StartDateDep,
    end_date: EndDateDep,
):
    per_day = (end_date - start_date).total_seconds() > 3 * 86400
    return crud.get_user_total_usage(
        db, db_user, start_date, end_date, per_day=per_day
    )


client_type_mime_type = {
    "sing-box": "application/json",
    "wireguard": "application/json",
    "clash-meta": "text/yaml",
    "clash": "text/yaml",
    "xray": "application/json",
    "yarx": "application/json",
    "v2ray": "text/plain",
    "links": "text/plain",
}


@router.get("/{username}/{key}/{client_type}")
def user_subscription_with_client_type(
    db: DBDep,
    db_user: SubUserDep,
    request: Request,
    client_type: str = Path(
        regex="^(sing-box|clash-meta|clash|xray|yarx|v2ray|links|wireguard)$"
    ),
    encrypt: str | None = Query(default=None, description="Encryption key for content"),
):
    """
    Subscription by client type; v2ray, xray, yarx, sing-box, clash and clash-meta formats supported
    Add ?encrypt=your_key to encrypt the response
    """

    user: UserResponse = UserResponse.model_validate(db_user)

    # Load settings from cache (60s TTL)
    subscription_settings = SubscriptionSettings.model_validate(
        get_subscription_settings_cached(db)
    )
    
    # Pre-load hosts ONCE (major optimization!)
    service_ids = [s.id for s in db_user.services]
    hosts = get_hosts_for_user(db, db_user.id, service_ids=service_ids)

    # Pre-load node coefficients for traffic limit labels
    node_coefficients = get_node_coefficients(db) if user.data_limit_reached else None

    # When only data_limit_reached (not expired/disabled), don't use placeholder
    only_data_limit = (
        user.data_limit_reached
        and user.enabled
        and not user.expired
    )
    use_placeholder = (
        not user.is_active
        and not only_data_limit
        and subscription_settings.placeholder_if_disabled
    )

    response_headers = {
        "content-disposition": f'attachment; filename="{user.username}"',
        "profile-web-page-url": str(request.url),
        "support-url": subscription_settings.support_link,
        "profile-title": encode_title(subscription_settings.profile_title),
        "profile-update-interval": str(subscription_settings.update_interval),
        "subscription-userinfo": "; ".join(
            f"{key}={val}"
            for key, val in get_subscription_user_info(user).items()
        ),
    }

    # Map yarx alias to xray format
    format_mapping = {
        "v2ray": "links",
        "yarx": "xray",
    }
    actual_format = format_mapping.get(client_type, client_type)
    
    conf = generate_subscription(
        user=db_user,
        config_format=actual_format,
        as_base64=client_type == "v2ray",
        use_placeholder=use_placeholder,
        placeholder_remark=subscription_settings.placeholder_remark,
        shuffle=subscription_settings.shuffle_configs,
        hosts=hosts,
        data_limit_reached=user.data_limit_reached,
        node_coefficients=node_coefficients,
    )
    
    # Encrypt content if encryption key is provided
    if encrypt:
        conf = encrypt_content(conf, encrypt)
        response_headers["X-Content-Encrypted"] = "true"
        # Change media type to text/plain for encrypted content
        media_type = "text/plain"
    else:
        media_type = client_type_mime_type[client_type]
    
    return Response(
        content=conf,
        media_type=media_type,
        headers=response_headers,
    )


# Alias router with /bus prefix
bus_router = APIRouter(prefix="/bus", tags=["Subscription"])


@bus_router.get("/{username}/{key}")
def bus_user_subscription(
    db_user: SubUserDep,
    request: Request,
    db: DBDep,
    user_agent: str = Header(default=""),
):
    """
    Subscription link (alias for /sub), result format depends on subscription settings
    """
    return user_subscription(db_user, request, db, user_agent)


@bus_router.get("/{username}/{key}/info", response_model=UserResponse)
def bus_user_subscription_info(db_user: SubUserDep):
    """
    User subscription info (alias for /sub)
    """
    return user_subscription_info(db_user)


@bus_router.get("/{username}/{key}/usage", response_model=TrafficUsageSeries)
def bus_user_get_usage(
    db_user: SubUserDep,
    db: DBDep,
    start_date: StartDateDep,
    end_date: EndDateDep,
):
    """
    User usage statistics (alias for /sub)
    """
    return user_get_usage(db_user, db, start_date, end_date)


@bus_router.get("/{username}/{key}/{client_type}")
def bus_user_subscription_with_client_type(
    db: DBDep,
    db_user: SubUserDep,
    request: Request,
    client_type: str = Path(
        regex="^(sing-box|clash-meta|clash|xray|yarx|v2ray|links|wireguard)$"
    ),
    encrypt: str | None = Query(default=None, description="Encryption key for content"),
):
    """
    Subscription by client type (alias for /sub); v2ray, xray, yarx, sing-box, clash and clash-meta formats supported
    Add ?encrypt=your_key to encrypt the response
    """
    return user_subscription_with_client_type(db, db_user, request, client_type, encrypt)
