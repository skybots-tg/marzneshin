"""Расхождение панели и ноды должно чиниться само и один раз.

До этой сверки потерянное обновление жило до следующего обрыва связи. Но
чинить по первому же несовпадению нельзя: между запросом отпечатка и выборкой
из БД проходит время, и обновление, пойманное на лету, честно даёт другой хэш.
Поэтому подтверждений два.
"""

import pytest

from app.marznode.registry import node_registry
from app.tasks import node_drift


class _Node:
    """Нода, чей отпечаток задаётся тестом."""

    def __init__(self, digest: str, count: int = 1, supports: bool = True):
        self.synced = True
        self._digest = digest
        self._count = count
        self._supports = supports
        self.resyncs = 0

    async def get_users_digest(self):
        if not self._supports:
            raise NotImplementedError("old marznode")
        return self._count, self._digest

    async def resync_users(self):
        self.resyncs += 1


@pytest.fixture
def fleet(monkeypatch):
    """Парк из одной ноды с id 77 и предсказуемым ожиданием из «БД»."""
    node_drift._streak.clear()
    node_drift._last_alert.clear()
    node_drift._unsupported.clear()
    node_drift._seen.clear()

    expected = {"value": (1, "expected-digest")}
    monkeypatch.setattr(node_drift, "_expected", lambda node_id: expected["value"])

    sent = []

    async def _fake_notify(node_id, node_count, want_count, repaired):
        sent.append((node_id, node_count, want_count, repaired))

    monkeypatch.setattr(node_drift, "_notify", _fake_notify)

    def register(node):
        node_registry.register(77, node)
        return node

    try:
        yield register, sent, expected
    finally:
        node_registry._nodes.pop(77, None)
        node_drift._streak.clear()
        node_drift._last_alert.clear()
        node_drift._unsupported.clear()
        node_drift._seen.clear()


@pytest.mark.asyncio
async def test_a_node_that_agrees_is_left_alone(fleet):
    register, sent, _ = fleet
    node = register(_Node("expected-digest"))

    await node_drift.check_node_drift()
    await node_drift.check_node_drift()

    assert node.resyncs == 0
    assert sent == []


@pytest.mark.asyncio
async def test_one_mismatch_is_a_suspicion_not_a_verdict(fleet):
    """Обновление, пойманное на лету, не должно тянуть полную выгрузку."""
    register, sent, _ = fleet
    node = register(_Node("something-else"))

    await node_drift.check_node_drift()

    assert node.resyncs == 0
    assert sent == []


@pytest.mark.asyncio
async def test_two_in_a_row_get_repaired_and_reported(fleet):
    register, sent, _ = fleet
    node = register(_Node("something-else", count=4))

    await node_drift.check_node_drift()
    await node_drift.check_node_drift()

    assert node.resyncs == 1
    assert sent == [(77, 4, 1, True)]


@pytest.mark.asyncio
async def test_a_streak_broken_by_agreement_starts_over(fleet):
    register, sent, expected = fleet
    node = register(_Node("something-else"))

    await node_drift.check_node_drift()
    expected["value"] = (1, "something-else")  # догнало
    await node_drift.check_node_drift()
    expected["value"] = (1, "expected-digest")  # и разошлось снова
    await node_drift.check_node_drift()

    assert node.resyncs == 0
    assert sent == []


@pytest.mark.asyncio
async def test_a_failed_repair_is_reported_as_such(fleet):
    register, sent, _ = fleet

    class _Broken(_Node):
        async def resync_users(self):
            raise RuntimeError("node went away mid-repair")

    register(_Broken("something-else", count=9))

    await node_drift.check_node_drift()
    await node_drift.check_node_drift()

    assert sent == [(77, 9, 1, False)]


@pytest.mark.asyncio
async def test_an_old_node_is_skipped_once_and_never_asked_again(fleet):
    register, sent, _ = fleet
    node = register(_Node("", supports=False))

    await node_drift.check_node_drift()
    await node_drift.check_node_drift()

    assert 77 in node_drift._unsupported
    assert node.resyncs == 0
    assert sent == []


@pytest.mark.asyncio
async def test_an_unsynced_node_is_not_judged(fleet):
    """Нода без живого стрима и так получит полную выгрузку при коннекте."""
    register, sent, _ = fleet
    node = register(_Node("something-else"))
    node.synced = False

    await node_drift.check_node_drift()
    await node_drift.check_node_drift()

    assert node.resyncs == 0
    assert sent == []


@pytest.mark.asyncio
async def test_an_unreachable_node_is_somebody_elses_alert(fleet):
    register, sent, _ = fleet

    class _Unreachable(_Node):
        async def get_users_digest(self):
            raise ConnectionError("no route to host")

    node = register(_Unreachable("irrelevant"))

    await node_drift.check_node_drift()
    await node_drift.check_node_drift()

    assert node.resyncs == 0
    assert sent == []


@pytest.mark.asyncio
async def test_a_node_announces_itself_once(fleet, caplog):
    """Во время раскатки нового marznode это единственный сигнал прогресса."""
    register, _, _ = fleet
    register(_Node("expected-digest"))

    with caplog.at_level("INFO"):
        await node_drift.check_node_drift()
        await node_drift.check_node_drift()

    said = [r for r in caplog.records if "сверка набора юзеров включилась" in r.message]
    assert len(said) == 1
