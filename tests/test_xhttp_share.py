"""XHTTP-ссылка несёт extra настоящим JSON и клиентский темп POST.

v2share сам кладёт extra python-словарём — после urlencode это
``{'headers': {}}`` в одинарных кавычках, не JSON. Шлюзу через хостинг IHC,
который банит IP за всплеск запросов, нужен ещё и клиентский темп packet-up
(scMinPostsIntervalMs), которого v2share не знает вовсе.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from v2share.data import XMuxSettings

from app.models.proxy import SplitHttpSettings as ApiSplitHttpSettings
from app.utils.xhttp_share import ShareData, ShareXrayConfig, SplitHttpSettings

import pytest
from pydantic import ValidationError

UUID_ = UUID("6b6f3c3e-1b4b-4a39-9f0c-3a2b1c0d9e8f")


def xhttp(settings, headers=None, remark="ELITE WEB", **kwargs):
    return ShareData(
        "vless",
        remark,
        "cdn.example.ru",
        443,
        uuid=UUID_,
        transport_type="splithttp",
        path="/secret",
        host="cdn.example.ru",
        sni="cdn.example.ru",
        tls="tls",
        fingerprint="firefox",
        splithttp_settings=settings,
        http_headers=headers,
        **kwargs,
    )


def link_params(data) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(data.to_link()).query).items()}


def test_extra_is_json_with_post_pacing():
    params = link_params(
        xhttp(
            SplitHttpSettings(
                mode="packet-up",
                sc_min_posts_interval_ms="100-200",
                sc_max_each_post_bytes="1000000",
                xmux=XMuxSettings(max_concurrency="16-32", max_request_times="600-900"),
            )
        )
    )
    assert params["type"] == "xhttp"
    assert params["mode"] == "packet-up"
    assert json.loads(params["extra"]) == {
        "scMinPostsIntervalMs": "100-200",
        "scMaxEachPostBytes": 1000000,
        "xmux": {"maxConcurrency": "16-32", "hMaxRequestTimes": "600-900"},
    }


def test_empty_headers_and_settings_give_no_extra():
    """Хост 550 до правки: только mode — extra в ссылке не нужен вовсе."""
    params = link_params(xhttp(SplitHttpSettings(mode="packet-up"), headers={}))
    assert "extra" not in params
    assert params["mode"] == "packet-up"


def test_real_headers_survive_as_json():
    params = link_params(
        xhttp(SplitHttpSettings(mode="packet-up"), headers={"X-Test": "1"})
    )
    assert json.loads(params["extra"]) == {"headers": {"X-Test": "1"}}


def test_empty_xmux_is_dropped():
    params = link_params(
        xhttp(SplitHttpSettings(mode="packet-up", padding_bytes="100-1000",
                                xmux=XMuxSettings()))
    )
    assert json.loads(params["extra"]) == {"xPaddingBytes": "100-1000"}


def test_xray_json_gets_the_same_tuning():
    config = ShareXrayConfig()
    config.add_proxies([
        xhttp(
            SplitHttpSettings(
                mode="packet-up",
                sc_min_posts_interval_ms="150",
                xmux=XMuxSettings(max_connections="4"),
            )
        )
    ])
    outbound = json.loads(config.render())[0]["outbounds"][0]
    settings = outbound["streamSettings"]["splithttpSettings"]
    assert settings["scMinPostsIntervalMs"] == 150
    assert settings["xmux"] == {"maxConnections": 4}
    assert settings["mode"] == "packet-up"
    assert "headers" not in settings


def test_xray_json_tunes_chained_hop():
    exit_hop = xhttp(SplitHttpSettings(mode="packet-up",
                                       sc_min_posts_interval_ms="120"),
                     remark="exit")
    entry = ShareData("vless", "entry", "1.2.3.4", 443, uuid=UUID_,
                      transport_type="tcp", next=exit_hop)
    outbounds = ShareXrayConfig.create_outbounds(entry)
    hop = next(o for o in outbounds if o["tag"] == "exit")
    assert hop["streamSettings"]["splithttpSettings"]["scMinPostsIntervalMs"] == 120


@pytest.mark.parametrize("value", ["100", "100-200"])
def test_api_accepts_ranges(value):
    s = ApiSplitHttpSettings(sc_min_posts_interval_ms=value,
                             sc_max_each_post_bytes=value)
    assert s.sc_min_posts_interval_ms == value


def test_api_rejects_garbage():
    with pytest.raises(ValidationError):
        ApiSplitHttpSettings(sc_min_posts_interval_ms="fast")
