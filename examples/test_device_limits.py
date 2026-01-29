"""
Пример использования API для управления лимитами устройств

Требования:
- pip install requests
"""

import requests
from typing import Optional

# Настройки
BASE_URL = "http://localhost:8000/api"
USERNAME = "admin"  # ваш admin username
PASSWORD = "admin"  # ваш admin password


class MarzneshinAPI:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url
        self.token = None
        self.login(username, password)
    
    def login(self, username: str, password: str):
        """Получить токен авторизации"""
        response = requests.post(
            f"{self.base_url}/admin/token",
            data={"username": username, "password": password}
        )
        response.raise_for_status()
        self.token = response.json()["access_token"]
        print(f"✓ Авторизация успешна")
    
    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}
    
    def create_user(self, username: str, device_limit: Optional[int] = None, 
                   service_ids: list = None) -> dict:
        """Создать пользователя с лимитом устройств"""
        data = {
            "username": username,
            "expire_strategy": "never",
            "service_ids": service_ids or [1],
        }
        if device_limit is not None:
            data["device_limit"] = device_limit
        
        response = requests.post(
            f"{self.base_url}/users",
            json=data,
            headers=self.headers
        )
        response.raise_for_status()
        user = response.json()
        print(f"✓ Создан пользователь: {username}, device_limit={device_limit}")
        return user
    
    def update_user_device_limit(self, username: str, device_limit: Optional[int]) -> dict:
        """Изменить лимит устройств пользователя"""
        data = {"device_limit": device_limit}
        response = requests.put(
            f"{self.base_url}/users/{username}",
            json=data,
            headers=self.headers
        )
        response.raise_for_status()
        user = response.json()
        print(f"✓ Обновлен лимит для {username}: device_limit={device_limit}")
        return user
    
    def get_user(self, username: str) -> dict:
        """Получить информацию о пользователе"""
        response = requests.get(
            f"{self.base_url}/users/{username}",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()
    
    def get_user_devices(self, username: str) -> list:
        """Получить список устройств пользователя"""
        response = requests.get(
            f"{self.base_url}/admin/users/{username}/devices",
            headers=self.headers
        )
        response.raise_for_status()
        devices = response.json()
        print(f"✓ Устройств пользователя {username}: {len(devices)}")
        return devices
    
    def get_device_details(self, username: str, device_id: int) -> dict:
        """Получить детальную информацию об устройстве"""
        response = requests.get(
            f"{self.base_url}/admin/users/{username}/devices/{device_id}",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()
    
    def delete_device(self, username: str, device_id: int):
        """Удалить устройство"""
        response = requests.delete(
            f"{self.base_url}/admin/users/{username}/devices/{device_id}",
            headers=self.headers
        )
        response.raise_for_status()
        print(f"✓ Устройство {device_id} удалено")
    
    def block_device(self, username: str, device_id: int, blocked: bool = True):
        """Заблокировать/разблокировать устройство"""
        response = requests.patch(
            f"{self.base_url}/admin/users/{username}/devices/{device_id}",
            json={"is_blocked": blocked},
            headers=self.headers
        )
        response.raise_for_status()
        action = "заблокировано" if blocked else "разблокировано"
        print(f"✓ Устройство {device_id} {action}")
    
    def update_device_name(self, username: str, device_id: int, display_name: str):
        """Изменить название устройства"""
        response = requests.patch(
            f"{self.base_url}/admin/users/{username}/devices/{device_id}",
            json={"display_name": display_name},
            headers=self.headers
        )
        response.raise_for_status()
        print(f"✓ Название устройства {device_id} изменено на '{display_name}'")
    
    def get_device_statistics(self, username: str) -> dict:
        """Получить статистику устройств пользователя"""
        response = requests.get(
            f"{self.base_url}/admin/users/{username}/devices/statistics",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()
    
    def delete_user(self, username: str):
        """Удалить пользователя"""
        response = requests.delete(
            f"{self.base_url}/users/{username}",
            headers=self.headers
        )
        response.raise_for_status()
        print(f"✓ Пользователь {username} удален")


def demo_device_limits():
    """Демонстрация работы с лимитами устройств"""
    print("=" * 60)
    print("ДЕМО: Управление лимитами устройств")
    print("=" * 60)
    
    api = MarzneshinAPI(BASE_URL, USERNAME, PASSWORD)
    test_username = "test_device_limit"
    
    try:
        # 1. Создать пользователя с лимитом 2 устройства
        print("\n1. Создание пользователя с device_limit=2")
        try:
            api.delete_user(test_username)  # Удалить если существует
        except:
            pass
        
        user = api.create_user(test_username, device_limit=2)
        print(f"   Username: {user['username']}")
        print(f"   Device limit: {user.get('device_limit', 'не установлен')}")
        
        # 2. Получить информацию о пользователе
        print("\n2. Получение информации о пользователе")
        user_info = api.get_user(test_username)
        print(f"   ID: {user_info['id']}")
        print(f"   Device limit: {user_info.get('device_limit', 'не установлен')}")
        print(f"   Status: {user_info['status']}")
        
        # 3. Изменить лимит на 5 устройств
        print("\n3. Изменение лимита на 5 устройств")
        api.update_user_device_limit(test_username, device_limit=5)
        
        # 4. Убрать лимит (установить null)
        print("\n4. Убираем лимит (без ограничений)")
        api.update_user_device_limit(test_username, device_limit=None)
        
        # 5. Снова установить лимит 3
        print("\n5. Устанавливаем лимит 3 устройства")
        api.update_user_device_limit(test_username, device_limit=3)
        
        # 6. Получить устройства пользователя
        print("\n6. Получение списка устройств пользователя")
        devices = api.get_user_devices(test_username)
        
        if devices:
            print(f"\n   Найдено устройств: {len(devices)}")
            for device in devices:
                print(f"\n   Устройство #{device['id']}:")
                print(f"     Client: {device.get('client_name', 'неизвестно')}")
                print(f"     Type: {device.get('client_type', 'неизвестно')}")
                print(f"     Display name: {device.get('display_name', 'не задано')}")
                print(f"     First seen: {device['first_seen_at']}")
                print(f"     Last seen: {device['last_seen_at']}")
                print(f"     Blocked: {device['is_blocked']}")
                print(f"     Upload: {device['total_upload_bytes'] / 1024 / 1024:.2f} MB")
                print(f"     Download: {device['total_download_bytes'] / 1024 / 1024:.2f} MB")
                print(f"     IPs count: {device['ip_count']}")
            
            # 7. Детальная информация об устройстве
            if devices:
                device_id = devices[0]['id']
                print(f"\n7. Детальная информация об устройстве {device_id}")
                device_details = api.get_device_details(test_username, device_id)
                print(f"   Fingerprint: {device_details['fingerprint'][:16]}...")
                
                if device_details.get('ips'):
                    print(f"\n   IP адреса устройства:")
                    for ip_info in device_details['ips'][:5]:  # Первые 5
                        print(f"     - {ip_info['ip']}")
                        if ip_info.get('country_code'):
                            print(f"       Country: {ip_info['country_code']}")
                        print(f"       Connections: {ip_info['connect_count']}")
                
                # 8. Переименовать устройство
                print(f"\n8. Переименование устройства")
                api.update_device_name(test_username, device_id, "My Test Device")
                
                # 9. Заблокировать устройство
                print(f"\n9. Блокировка устройства")
                api.block_device(test_username, device_id, blocked=True)
                
                # 10. Разблокировать устройство
                print(f"\n10. Разблокировка устройства")
                api.block_device(test_username, device_id, blocked=False)
        else:
            print("   У пользователя пока нет зарегистрированных устройств")
            print("   Устройства появятся после первого подключения")
        
        # 11. Статистика устройств
        print("\n11. Статистика устройств пользователя")
        try:
            stats = api.get_device_statistics(test_username)
            print(f"   Всего устройств: {stats['total_devices']}")
            print(f"   Активных устройств: {stats['active_devices']}")
            print(f("   Заблокированных: {stats['blocked_devices']}")
            print(f"   Уникальных IP: {stats['total_ips']}")
            print(f"   Страны: {', '.join(stats.get('unique_countries', []))}")
            print(f"   Общий трафик: {stats['total_traffic'] / 1024 / 1024:.2f} MB")
        except Exception as e:
            print(f"   Ошибка получения статистики: {e}")
        
        print("\n" + "=" * 60)
        print("✓ ДЕМО завершено успешно!")
        print("=" * 60)
        
        # Опционально: удалить тестового пользователя
        # api.delete_user(test_username)
        
    except Exception as e:
        print(f"\n✗ Ошибка: {e}")
        import traceback
        traceback.print_exc()


def demo_device_limit_enforcement():
    """Демонстрация работы ограничения устройств"""
    print("\n" + "=" * 60)
    print("ДЕМО: Проверка работы ограничения устройств")
    print("=" * 60)
    
    api = MarzneshinAPI(BASE_URL, USERNAME, PASSWORD)
    test_username = "test_limit_check"
    
    try:
        # Создать пользователя с жестким лимитом 1 устройство
        print("\n1. Создание пользователя с device_limit=1")
        try:
            api.delete_user(test_username)
        except:
            pass
        
        api.create_user(test_username, device_limit=1)
        
        print("\n2. Проверка текущих устройств")
        devices = api.get_user_devices(test_username)
        print(f"   Текущее количество устройств: {len(devices)}")
        
        if len(devices) >= 1:
            print("\n   ⚠ У пользователя уже есть устройство(а)")
            print("   При попытке подключения с нового устройства:")
            print("   - Подключение может работать (зависит от настроек прокси)")
            print("   - Новое устройство НЕ будет зарегистрировано в системе")
            print("   - В логах появится: 'Device limit reached'")
        else:
            print("\n   ℹ У пользователя пока нет устройств")
            print("   Первое устройство будет зарегистрировано")
            print("   Второе устройство будет заблокировано при регистрации")
        
        print("\n3. Рекомендации:")
        print("   - Для удаления старого устройства: DELETE /devices/{device_id}")
        print("   - Для блокировки: PATCH /devices/{device_id} {'is_blocked': true}")
        print("   - Для увеличения лимита: PUT /users/{username} {'device_limit': 3}")
        
    except Exception as e:
        print(f"\n✗ Ошибка: {e}")


if __name__ == "__main__":
    print("""
    Этот скрипт демонстрирует работу с API лимитов устройств.
    
    Перед запуском убедитесь:
    1. Marzneshin запущен и доступен
    2. Применена миграция БД (alembic upgrade head)
    3. Настройки BASE_URL, USERNAME, PASSWORD корректны
    """)
    
    input("Нажмите Enter для продолжения...")
    
    # Запустить демо
    demo_device_limits()
    
    # Опционально: проверка ограничений
    print("\n")
    run_limit_check = input("Запустить демо проверки ограничений? (y/n): ")
    if run_limit_check.lower() == 'y':
        demo_device_limit_enforcement()






