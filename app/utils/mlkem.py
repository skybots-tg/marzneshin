import json
import os
import subprocess
from functools import lru_cache
from typing import NamedTuple, Optional


class MlkemKeyPair(NamedTuple):
    public_key: str
    private_key: str


class MlkemError(RuntimeError):
    """Ошибки при работе с ML-KEM и бинарём Xray."""


def _get_xray_binary() -> str:
    """
    Возвращает путь к бинарю Xray.

    Приоритет:
    1. Переменная окружения XRAY_BINARY
    2. Просто 'xray' (должен быть в PATH)
    """
    return os.getenv("XRAY_BINARY", "xray")


def _run_xray_mlkem(variant: str = "mlkem768") -> dict:
    """
    Вызывает `xray <variant>` и возвращает разобранный вывод.

    В новых версиях Xray обычно возвращается JSON с полями `publicKey` и
    `privateKey`. На всякий случай поддерживаем также простой текстовый
    вывод, где ключи могут быть выведены построчно.
    """
    command = _get_xray_binary()

    try:
        result = subprocess.run(
            [command, variant],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise MlkemError(
            "Бинарь Xray не найден. Установите Xray и задайте переменную "
            "окружения XRAY_BINARY или добавьте бинарь в PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise MlkemError(
            f"Команда '{command} {variant}' завершилась с ошибкой: {stderr}"
        ) from exc

    stdout = (result.stdout or "").strip()
    if not stdout:
        raise MlkemError("Команда Xray для ML-KEM вернула пустой вывод")

    # Пробуем сначала JSON
    try:
        data = json.loads(stdout)
        return {"mode": "json", "data": data}
    except json.JSONDecodeError:
        # Фоллбек на произвольный текст, разберём позже
        return {"mode": "raw", "data": stdout}


def _parse_mlkem_output(payload: dict) -> MlkemKeyPair:
    """
    Преобразует вывод Xray в пару ключей.

    Ожидаемые варианты:
    1) JSON с полями `publicKey` и `privateKey`
    2) Текст, в котором первые две непустые строки — публичный и приватный
       ключ соответственно.
    """
    mode = payload.get("mode")
    data = payload.get("data")

    if mode == "json" and isinstance(data, dict):
        public_key = data.get("publicKey") or data.get("public_key")
        private_key = data.get("privateKey") or data.get("private_key")
        if public_key and private_key:
            return MlkemKeyPair(public_key=public_key, private_key=private_key)

    if mode == "raw" and isinstance(data, str):
        lines = [line.strip() for line in data.splitlines() if line.strip()]
        if len(lines) >= 2:
            return MlkemKeyPair(public_key=lines[0], private_key=lines[1])

    raise MlkemError(f"Не удалось распознать вывод Xray ML-KEM: {payload!r}")


@lru_cache(maxsize=16)
def generate_mlkem_keypair(variant: str = "mlkem768") -> MlkemKeyPair:
    """
    Генерирует пару ML-KEM ключей через Xray и кеширует результат.

    Кеширование уменьшает нагрузку, если панель часто создаёт хосты с
    одинаковыми параметрами ML-KEM. При необходимости можно сбросить кеш
    через generate_mlkem_keypair.cache_clear().
    """
    payload = _run_xray_mlkem(variant=variant)
    return _parse_mlkem_output(payload)


def ensure_mlkem_keys(
    public_key: Optional[str],
    private_key: Optional[str],
    variant: str = "mlkem768",
) -> MlkemKeyPair:
    """
    Утилита для моделей/CRUD: если ключи отсутствуют, генерирует новые.

    Возвращает:
        MlkemKeyPair(public_key, private_key)
    """
    if public_key and private_key:
        return MlkemKeyPair(public_key=public_key, private_key=private_key)

    return generate_mlkem_keypair(variant=variant)


