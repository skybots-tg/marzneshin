# Реализация блокировки устройств на уровне Marzneshin

## ✅ Что сделано

### 1. Расширен protobuf протокол
**Файл:** `app/marznode/marznode.proto`

Добавлены поля в сообщение `User`:
```protobuf
message User {
  uint32 id = 1;
  string username = 2;
  string key = 3;
  optional uint32 device_limit = 4;              // Лимит устройств
  repeated string allowed_fingerprints = 5;      // Разрешенные fingerprints
  bool enforce_device_limit = 6;                  // Включить проверку
}
```

### 2. Обновлена синхронизация пользователей

**Файлы изменены:**
- `app/marznode/operations.py` - добавлена функция `_get_allowed_fingerprints()`
- `app/marznode/base.py` - обновлена сигнатура `update_user()`
- `app/marznode/grpcio.py` - передача device_limit и fingerprints в proto
- `app/marznode/grpclib.py` - аналогично для grpclib
- `app/marznode/database.py` - получение device_limit и fingerprints при `list_users()`

### 3. Добавлена настройка

**Файл:** `app/config/env.py`
```python
ENFORCE_DEVICE_LIMITS_ON_PROXY = config("ENFORCE_DEVICE_LIMITS_ON_PROXY", default=True, cast=bool)
```

**Файл:** `.env.example`
```bash
# ENFORCE_DEVICE_LIMITS_ON_PROXY=true
```

### 4. Автоматическая ресинхронизация

**Файл:** `app/routes/device.py`
- При удалении устройства → автоматическая синхронизация с узлами
- При блокировке/разблокировке → автоматическая синхронизация

**Файл:** `app/utils/device_tracker.py`
- При создании нового устройства → автоматическая синхронизация

## 🔄 Следующие шаги

### 1. Регенерировать protobuf файлы

**ВАЖНО:** После изменения `marznode.proto` нужно регенерировать Python файлы:

```bash
cd app/marznode
python -m grpc_tools.protoc -I. \
    --python_out=. \
    --grpc_python_out=. \
    --pyi_out=. \
    marznode.proto
```

Или использовать скрипт:
```bash
./regenerate_proto.sh
```

### 2. Применить миграцию БД

```bash
# Docker
docker-compose exec marzneshin alembic upgrade head

# Локально
alembic upgrade head
```

### 3. Перезапустить Marzneshin

```bash
docker-compose restart marzneshin
```

## 🛠️ Изменения в marznode (со стороны marznode)

Теперь **на стороне marznode** нужно добавить проверку fingerprint при подключении:

### 1. Обработка новых полей proto

После регенерации proto файлов в marznode, данные будут доступны:
```go
user := userConfig.GetUser()
deviceLimit := user.GetDeviceLimit()
allowedFingerprints := user.GetAllowedFingerprints()
enforceLimit := user.GetEnforceDeviceLimit()
```

### 2. Проверка при подключении

В обработчике подключений добавить:
```go
func (h *UserHandler) OnUserConnect(req *ConnectRequest) error {
    user := h.getUserByKey(req.UserKey)
    
    if user.EnforceDeviceLimit && user.DeviceLimit != nil {
        fingerprint := calculateDeviceFingerprint(
            req.ClientName,
            req.TLSFingerprint,
            req.UserAgent,
        )
        
        if !contains(user.AllowedFingerprints, fingerprint) {
            log.Warn().
                Str("username", user.Username).
                Str("fingerprint", fingerprint).
                Msg("Connection blocked: device not in allowed list")
            
            return errors.New("device not allowed: limit exceeded")
        }
    }
    
    // Продолжить обычную обработку
    return h.processConnection(req)
}
```

### 3. Вычисление fingerprint

**ВАЖНО:** Алгоритм должен совпадать с Python версией:

```go
func calculateDeviceFingerprint(clientName, tlsFingerprint, userAgent string) string {
    // Важно: user_id не используется в текущей версии
    components := []string{
        "",  // user_id placeholder
        clientName,
        tlsFingerprint,
        "",  // os_guess placeholder
        userAgent,
    }
    
    source := strings.Join(components, "|")
    hash := sha256.Sum256([]byte(source))
    return hex.EncodeToString(hash[:])
}
```

## 📊 Как это работает сейчас

### 1. Создание нового устройства
```
User connects → Marzneshin tracks device → Create device in DB
                                              ↓
                                    Check device_limit
                                              ↓
                        If OK → Create + Sync with nodes
                        If NO → Reject (not created)
```

### 2. После синхронизации с узлами

Marzneshin отправляет на узлы:
```json
{
  "user": {
    "id": 123,
    "username": "john_doe",
    "key": "...",
    "device_limit": 3,
    "allowed_fingerprints": [
      "abc123...",
      "def456...",
      "ghi789..."
    ],
    "enforce_device_limit": true
  },
  "inbounds": [...]
}
```

### 3. Удаление/блокировка устройства
```
Admin deletes device → Remove from DB → Sync with nodes
                                              ↓
                        Nodes update allowed_fingerprints list
                                              ↓
                          Device can no longer connect
```

## 🧪 Тестирование

### 1. Проверить передачу данных

После регенерации proto файлов и перезапуска, проверить логи узла:
```bash
# Должны появиться логи с device_limit и allowed_fingerprints
docker logs marznode-1 | grep "device_limit"
```

### 2. Проверить создание устройства

```bash
# Создать пользователя с лимитом 2
curl -X PUT "http://localhost:8000/api/users/testuser" \
  -H "Authorization: Bearer TOKEN" \
  -d '{"device_limit": 2}'

# Подключиться с первого устройства → должно пройти
# Подключиться со второго устройства → должно пройти
# Подключиться с третьего устройства → должно блокироваться на узле (если marznode реализован)
```

### 3. Проверить удаление

```bash
# Удалить первое устройство
curl -X DELETE "http://localhost:8000/api/admin/users/testuser/devices/1" \
  -H "Authorization: Bearer TOKEN"

# Попытка подключения с этого устройства должна блокироваться
```

## ⚙️ Настройка

### Включить проверку на уровне прокси

```bash
# .env
ENFORCE_DEVICE_LIMITS_ON_PROXY=true
```

### Отключить (только учет на уровне Marzneshin)

```bash
# .env
ENFORCE_DEVICE_LIMITS_ON_PROXY=false
```

## 📝 Файлы изменений

### Marzneshin (сделано):
1. ✅ `app/marznode/marznode.proto` - расширен протокол
2. ✅ `app/marznode/operations.py` - добавлена передача устройств
3. ✅ `app/marznode/base.py` - обновлена сигнатура
4. ✅ `app/marznode/grpcio.py` - передача в proto (grpcio)
5. ✅ `app/marznode/grpclib.py` - передача в proto (grpclib)
6. ✅ `app/marznode/database.py` - получение device_limit и fingerprints
7. ✅ `app/routes/device.py` - автосинхронизация при изменении
8. ✅ `app/utils/device_tracker.py` - автосинхронизация при создании
9. ✅ `app/config/env.py` - настройка ENFORCE_DEVICE_LIMITS_ON_PROXY
10. ✅ `.env.example` - документация настройки
11. ✅ `app/db/migrations/versions/20241219_add_device_limit.py` - миграция БД
12. ✅ `app/models/user.py` - модель User с device_limit
13. ✅ `app/db/models.py` - таблица users с device_limit

### Marznode (требуется):
1. ⏳ Регенерировать proto файлы (автоматически)
2. ⏳ Добавить проверку fingerprint в обработчик подключений
3. ⏳ Реализовать функцию calculateDeviceFingerprint
4. ⏳ Обновить конфигурацию пользователей при синхронизации

## 🎯 Итог

**Со стороны Marzneshin** всё готово:
- ✅ Протокол расширен
- ✅ Данные передаются на узлы
- ✅ Автоматическая синхронизация работает
- ✅ Настройка добавлена

**Со стороны marznode** требуется:
- ⏳ Обработать новые поля proto
- ⏳ Добавить проверку при подключении
- ⏳ Реализовать вычисление fingerprint (идентично Python)

После реализации на стороне marznode, система будет:
1. Отслеживать устройства на уровне Marzneshin
2. Передавать список разрешенных устройств на узлы
3. Блокировать подключения неразрешенных устройств на уровне прокси






