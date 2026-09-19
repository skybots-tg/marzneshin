"""Обновление страницы не на главной не должно давать 404.

Дашборд маршрутизируется на клиенте: `/dashboard/nodes` существует только
после того, как загрузился `index.html`. ``StaticFiles(html=True)`` об этом
не знает и ищет на диске файл с таким именем, поэтому любая ссылка на раздел
и любое нажатие F5 отвечали ``{"detail": "Not Found"}``.
"""

import pytest
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.marzneshin import SPAStaticFiles


class _Recorder(SPAStaticFiles):
    """Подменяет обращение к диску: что попросили и что там лежит."""

    def __init__(self, existing: set[str]):
        self.existing = existing
        self.asked: list[str] = []

    async def get_response(self, path: str, scope):  # type: ignore[override]
        return await SPAStaticFiles.get_response(self, path, scope)

    async def _super_get_response(self, path: str, scope):
        self.asked.append(path)
        if path in self.existing:
            return f"file:{path}"
        raise StarletteHTTPException(status_code=404)


@pytest.fixture(autouse=True)
def _patch_parent(monkeypatch):
    async def fake(self, path, scope):
        return await self._super_get_response(path, scope)

    monkeypatch.setattr(
        "starlette.staticfiles.StaticFiles.get_response", fake, raising=True
    )


@pytest.mark.asyncio
async def test_existing_file_is_served_as_is():
    files = _Recorder({"index.html", "static/app.js"})
    assert await files.get_response("static/app.js", {}) == "file:static/app.js"
    assert files.asked == ["static/app.js"]


@pytest.mark.asyncio
async def test_a_client_route_falls_back_to_index():
    files = _Recorder({"index.html"})
    assert await files.get_response("nodes", {}) == "file:index.html"
    assert files.asked == ["nodes", "index.html"]


@pytest.mark.asyncio
async def test_a_nested_client_route_falls_back_too():
    files = _Recorder({"index.html"})
    assert await files.get_response("nodes/45/edit", {}) == "file:index.html"


@pytest.mark.asyncio
async def test_other_errors_are_not_swallowed():
    class _Forbidden(_Recorder):
        async def _super_get_response(self, path, scope):
            raise StarletteHTTPException(status_code=403)

    with pytest.raises(StarletteHTTPException) as err:
        await _Forbidden(set()).get_response("nodes", {})
    assert err.value.status_code == 403
