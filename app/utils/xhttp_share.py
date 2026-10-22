"""XHTTP в подписке: ``extra`` настоящим JSON и клиентский темп POST.

v2share 0.1.0b31 кладёт ``extra`` в ссылку python-словарём, и ``urlencode``
превращает его в ``{'headers': {}}`` — одинарные кавычки, не JSON, клиенты
такую ссылку разбирают как попало. Ещё v2share не знает клиентских полей
packet-up, которыми режется частота запросов: ``scMinPostsIntervalMs`` и
``scMaxEachPostBytes``. Шлюз через виртуальный хостинг IHC банит IP клиента
целиком при всплеске ~90 запросов/с, и за мобильным CGNAT такой бан отрезает
всех, кто сидит на том же адресе, — темп нужно задавать на стороне клиента.

Обе беды правятся здесь, без правки site-packages: подклассы V2Data и
XrayConfig собирают ``extra``/``splithttpSettings`` заново.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from v2share import V2Data, XrayConfig
from v2share.data import SplitHttpSettings as V2SplitHttpSettings


@dataclass
class SplitHttpSettings(V2SplitHttpSettings):
    sc_min_posts_interval_ms: Optional[str] = None
    sc_max_each_post_bytes: Optional[str] = None


def _range_value(value):
    """``"100"`` → 100, ``"100-200"`` остаётся строкой: так xray понимает оба."""
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def _without_empty(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None and v != {}}


def xhttp_xmux(settings: V2SplitHttpSettings) -> dict:
    xmux = settings.xmux
    if xmux is None:
        return {}
    return _without_empty(
        {
            "maxConcurrency": _range_value(xmux.max_concurrency),
            "maxConnections": _range_value(xmux.max_connections),
            "cMaxReuseTimes": _range_value(xmux.max_reuse_times),
            "cMaxLifetimeMs": _range_value(xmux.max_lifetime),
            "hMaxRequestTimes": _range_value(xmux.max_request_times),
            "hKeepAlivePeriod": xmux.keep_alive_period,
        }
    )


def xhttp_client_tuning(settings: V2SplitHttpSettings) -> dict:
    """Клиентские поля XHTTP, которых нет в v2share или которые он теряет."""
    return _without_empty(
        {
            "xPaddingBytes": _range_value(settings.padding_bytes),
            "scMinPostsIntervalMs": _range_value(
                getattr(settings, "sc_min_posts_interval_ms", None)
            ),
            "scMaxEachPostBytes": _range_value(
                getattr(settings, "sc_max_each_post_bytes", None)
            ),
        }
    )


def xhttp_extra(settings: V2SplitHttpSettings, headers: dict | None) -> dict:
    """Содержимое ``extra`` для ссылки: только заданные поля, пустых нет."""
    return _without_empty(
        {
            "headers": headers or None,
            **xhttp_client_tuning(settings),
            "noGRPCHeader": settings.no_grpc_header,
            "xmux": xhttp_xmux(settings),
        }
    )


class ShareData(V2Data):
    def _apply_trojan_vless_transport(self, payload):
        super()._apply_trojan_vless_transport(payload)
        # v2share кладёт extra только для splithttp с настройками
        if "extra" not in payload:
            return
        extra = xhttp_extra(self.splithttp_settings, self.http_headers)
        if extra:
            payload["extra"] = json.dumps(
                extra, ensure_ascii=False, separators=(",", ":")
            )
        else:
            del payload["extra"]


class ShareXrayConfig(XrayConfig):
    @staticmethod
    def create_outbounds(data: V2Data):
        outbounds = XrayConfig.create_outbounds(data)
        # Цепочка next строится внутри v2share базовым классом, поэтому
        # каждое звено ищем по тегу (тег outbound = remark звена).
        link = data
        while link is not None:
            settings = link.splithttp_settings
            if link.transport_type == "splithttp" and settings is not None:
                for outbound in outbounds:
                    stream = outbound.get("streamSettings") or {}
                    xhttp = stream.get("splithttpSettings")
                    if outbound["tag"] == link.remark and xhttp is not None:
                        _tune_xhttp_settings(xhttp, settings)
                        break
            link = link.next
        return outbounds


def _tune_xhttp_settings(xhttp: dict, settings: V2SplitHttpSettings) -> None:
    if not xhttp.get("headers"):
        xhttp.pop("headers", None)
    xmux = xhttp_xmux(settings)
    if xmux:
        xhttp["xmux"] = xmux
    else:
        xhttp.pop("xmux", None)
    xhttp.update(xhttp_client_tuning(settings))
