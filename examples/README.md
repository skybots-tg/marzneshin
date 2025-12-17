# Примеры использования Device History API

Эта папка содержит примеры кода для работы с новыми API методами истории устройств.

## Файлы

### 1. `test_device_history.py`

Демонстрационный скрипт для тестирования gRPC методов напрямую.

**Требования:**
- Запуск из корня проекта Marzneshin
- Доступ к внутренним модулям (`app.marznode`)
- Работающие и подключенные ноды

**Функции:**
- Получение устройств конкретного пользователя
- Получение всех устройств с ноды
- Проверка мультилогина
- Анализ трафика по устройствам
- Обнаружение аномалий

**Использование:**

```bash
# Из корня проекта
python examples/test_device_history.py

# Отредактируйте NODE_ID и USER_ID в скрипте перед запуском
```

**Пример вывода:**

```
================================================================================
🚀 Device History API - Тестовые сценарии
================================================================================

✅ Доступно нод: 2
   • Нода 1
   • Нода 2

================================================================================
📱 Получение устройств пользователя 123 с ноды 1
   Только активные: False
================================================================================

✅ Найдено устройств: 3
   User ID: 123

   Устройство #1:
   ├─ IP адрес: 192.168.1.100
   ├─ Клиент: v2rayNG
   ├─ User Agent: Clash/1.11.0
   ├─ Протокол: vless
   ├─ TLS Fingerprint: chrome
   ├─ Первое подключение: 2024-12-15 14:30:00
   ├─ Последнее подключение: 2024-12-17 10:45:23
   ├─ Активно: 🟢 Да
   ├─ Общий трафик: 1.50 GB
   ├─ ↑ Отправлено: 750.00 MB
   └─ ↓ Получено: 750.00 MB
...
```

---

### 2. `device_api_client.py`

HTTP клиент для работы с REST API endpoint'ами.

**Требования:**
- Python 3.7+
- Библиотека `requests`: `pip install requests`
- Bearer токен администратора

**Использование:**

```bash
# Установка зависимостей
pip install requests

# Помощь
python examples/device_api_client.py --help

# Получить устройства пользователя
python examples/device_api_client.py \
  --url https://your-panel.com \
  --token YOUR_ADMIN_TOKEN \
  user-devices --node-id 1 --user-id 123

# Только активные устройства
python examples/device_api_client.py \
  --url https://your-panel.com \
  --token YOUR_ADMIN_TOKEN \
  user-devices --node-id 1 --user-id 123 --active-only

# Получить все устройства
python examples/device_api_client.py \
  --url https://your-panel.com \
  --token YOUR_ADMIN_TOKEN \
  all-devices --node-id 1

# С детальной информацией
python examples/device_api_client.py \
  --url https://your-panel.com \
  --token YOUR_ADMIN_TOKEN \
  all-devices --node-id 1 --details

# Проверить мультилогин
python examples/device_api_client.py \
  --url https://your-panel.com \
  --token YOUR_ADMIN_TOKEN \
  check-multilogin --node-id 1 --user-id 123 --max-devices 3

# Анализ трафика
python examples/device_api_client.py \
  --url https://your-panel.com \
  --token YOUR_ADMIN_TOKEN \
  analyze-traffic --node-id 1 --user-id 123 --top 5

# Вывод в JSON
python examples/device_api_client.py \
  --url https://your-panel.com \
  --token YOUR_ADMIN_TOKEN \
  user-devices --node-id 1 --user-id 123 --json
```

**Команды:**

| Команда | Описание |
|---------|----------|
| `user-devices` | Получить устройства конкретного пользователя |
| `all-devices` | Получить все устройства с ноды |
| `check-multilogin` | Проверить нарушение лимита устройств |
| `analyze-traffic` | Проанализировать трафик по устройствам |

**Опции:**

| Опция | Описание |
|-------|----------|
| `--url` | Базовый URL панели (по умолчанию: http://localhost:8000) |
| `--token` | Bearer токен администратора (обязательно) |
| `--node-id` | ID ноды |
| `--user-id` | ID пользователя |
| `--active-only` | Показать только активные устройства |
| `--details` | Показать детальную информацию |
| `--json` | Вывести результат в JSON формате |
| `--max-devices` | Максимальное количество устройств для multilogin |
| `--top` | Количество топ устройств для анализа трафика |

---

## Интеграция в свой код

### Python

```python
from examples.device_api_client import DeviceAPIClient

# Создать клиент
client = DeviceAPIClient(
    base_url='https://your-panel.com',
    token='YOUR_ADMIN_TOKEN'
)

# Получить устройства пользователя
data = client.get_user_devices(node_id=1, user_id=123, active_only=True)

# Напечатать информацию
client.print_devices(data)

# Проверить мультилогин
violation = client.check_multilogin(node_id=1, user_id=123, max_devices=3)

if violation:
    print("⚠️ Обнаружен мультилогин!")
```

### JavaScript/TypeScript

```javascript
const baseUrl = 'https://your-panel.com';
const token = 'YOUR_ADMIN_TOKEN';

// Получить устройства пользователя
async function getUserDevices(nodeId, userId, activeOnly = false) {
  const url = `${baseUrl}/api/nodes/${nodeId}/devices/${userId}`;
  const params = new URLSearchParams({ active_only: activeOnly });
  
  const response = await fetch(`${url}?${params}`, {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });
  
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  
  return await response.json();
}

// Использование
const data = await getUserDevices(1, 123, true);

console.log(`User ${data.uid} has ${data.devices.length} active devices`);

data.devices.forEach(device => {
  console.log(`- ${device.remote_ip} (${device.client_name})`);
});
```

### cURL

```bash
# Базовые переменные
BASE_URL="https://your-panel.com"
TOKEN="YOUR_ADMIN_TOKEN"

# Получить устройства пользователя
curl -X GET "${BASE_URL}/api/nodes/1/devices/123?active_only=true" \
  -H "Authorization: Bearer ${TOKEN}" \
  | jq '.'

# Только IP адреса
curl -X GET "${BASE_URL}/api/nodes/1/devices/123" \
  -H "Authorization: Bearer ${TOKEN}" \
  | jq '.devices[].remote_ip'

# Подсчитать трафик
curl -X GET "${BASE_URL}/api/nodes/1/devices/123" \
  -H "Authorization: Bearer ${TOKEN}" \
  | jq '[.devices[].total_usage] | add'

# Получить все устройства
curl -X GET "${BASE_URL}/api/nodes/1/devices" \
  -H "Authorization: Bearer ${TOKEN}" \
  | jq '.users | length'
```

---

## Автоматизация

### Cron задача для проверки мультилогина

```bash
#!/bin/bash
# /etc/cron.d/check-multilogin
# Проверять каждые 5 минут

*/5 * * * * /usr/bin/python3 /path/to/device_api_client.py \
  --url https://your-panel.com \
  --token YOUR_TOKEN \
  check-multilogin --node-id 1 --user-id 123 --max-devices 3 \
  || echo "Multilogin detected for user 123" | mail -s "Alert" admin@example.com
```

### Systemd service для мониторинга

```ini
# /etc/systemd/system/device-monitor.service
[Unit]
Description=Device History Monitor
After=network.target

[Service]
Type=simple
User=marzneshin
WorkingDirectory=/opt/marzneshin
ExecStart=/usr/bin/python3 /opt/marzneshin/examples/monitor_devices.py
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
```

### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY examples/ ./examples/

CMD ["python", "examples/device_api_client.py", \
     "--url", "${PANEL_URL}", \
     "--token", "${ADMIN_TOKEN}", \
     "all-devices", "--node-id", "1"]
```

---

## Устранение неполадок

### Ошибка: "Module 'requests' not found"

```bash
pip install requests
```

### Ошибка: "401 Unauthorized"

Проверьте, что токен валидный и имеет sudo права:

```bash
curl -X GET "https://your-panel.com/api/admin" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Ошибка: "404 Node not found"

Убедитесь, что нода с указанным ID существует и подключена:

```bash
curl -X GET "https://your-panel.com/api/nodes" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Ошибка: "502 Bad Gateway"

Возможные причины:
- Нода недоступна
- Версия Marznode не поддерживает новые методы
- Проблемы с сетью

Проверьте статус ноды в панели управления.

---

## Дополнительные ресурсы

- [Полная документация API](../docs/NODE_DEVICES_API.md)
- [Руководство по интеграции](../docs/DEVICE_HISTORY_INTEGRATION.md)
- [Changelog](../docs/CHANGELOG_DEVICE_HISTORY.md)

## Поддержка

Если у вас возникли проблемы:

1. Проверьте логи панели и ноды
2. Убедитесь, что версии совместимы
3. Создайте issue в GitHub

---

**Примечание**: Не забудьте заменить `YOUR_ADMIN_TOKEN` на реальный токен администратора!

