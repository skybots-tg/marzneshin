#!/usr/bin/env python3
"""
HTTP клиент для Device History API

Простой клиент для работы с REST API endpoint'ами истории устройств.

Использование:
    python device_api_client.py --help
    
    # Получить устройства пользователя
    python device_api_client.py user-devices --node-id 1 --user-id 123
    
    # Получить все устройства
    python device_api_client.py all-devices --node-id 1
    
    # Проверить мультилогин
    python device_api_client.py check-multilogin --node-id 1 --user-id 123 --max-devices 3
"""

import argparse
import json
import sys
from typing import Optional, Dict, List
from datetime import datetime

try:
    import requests
except ImportError:
    print("❌ Требуется библиотека requests. Установите: pip install requests")
    sys.exit(1)


class DeviceAPIClient:
    """Клиент для Device History API"""
    
    def __init__(self, base_url: str, token: str):
        """
        Инициализация клиента
        
        Args:
            base_url: Базовый URL панели (например: https://panel.example.com)
            token: Bearer токен администратора
        """
        self.base_url = base_url.rstrip('/')
        self.headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
    
    def _format_bytes(self, bytes_value: int) -> str:
        """Форматировать байты в читаемый вид"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.2f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.2f} PB"
    
    def _format_timestamp(self, timestamp: int) -> str:
        """Форматировать Unix timestamp"""
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    
    def get_user_devices(
        self, 
        node_id: int, 
        user_id: int, 
        active_only: bool = False
    ) -> Dict:
        """
        Получить устройства конкретного пользователя
        
        Args:
            node_id: ID ноды
            user_id: ID пользователя
            active_only: Только активные устройства
            
        Returns:
            Словарь с данными устройств
        """
        url = f"{self.base_url}/api/nodes/{node_id}/devices/{user_id}"
        params = {'active_only': active_only}
        
        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ Ошибка при запросе: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"   Статус код: {e.response.status_code}")
                print(f"   Ответ: {e.response.text}")
            sys.exit(1)
    
    def get_all_devices(self, node_id: int) -> Dict:
        """
        Получить все устройства с ноды
        
        Args:
            node_id: ID ноды
            
        Returns:
            Словарь с данными всех устройств
        """
        url = f"{self.base_url}/api/nodes/{node_id}/devices"
        
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ Ошибка при запросе: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"   Статус код: {e.response.status_code}")
                print(f"   Ответ: {e.response.text}")
            sys.exit(1)
    
    def print_devices(self, data: Dict, show_inactive: bool = True):
        """
        Красиво напечатать информацию об устройствах
        
        Args:
            data: Данные устройств
            show_inactive: Показывать неактивные устройства
        """
        devices = data.get('devices', [])
        
        if not devices:
            print("   (нет устройств)")
            return
        
        print(f"\n✅ Найдено устройств: {len(devices)}")
        print(f"   User ID: {data.get('uid')}\n")
        
        for idx, device in enumerate(devices, 1):
            if not show_inactive and not device.get('is_active'):
                continue
            
            print(f"   Устройство #{idx}:")
            print(f"   ├─ IP адрес: {device['remote_ip']}")
            print(f"   ├─ Клиент: {device['client_name']}")
            
            if device.get('user_agent'):
                print(f"   ├─ User Agent: {device['user_agent']}")
            if device.get('protocol'):
                print(f"   ├─ Протокол: {device['protocol']}")
            if device.get('tls_fingerprint'):
                print(f"   ├─ TLS Fingerprint: {device['tls_fingerprint']}")
            
            print(f"   ├─ Первое подключение: {self._format_timestamp(device['first_seen'])}")
            print(f"   ├─ Последнее подключение: {self._format_timestamp(device['last_seen'])}")
            print(f"   ├─ Активно: {'🟢 Да' if device['is_active'] else '🔴 Нет'}")
            print(f"   ├─ Общий трафик: {self._format_bytes(device['total_usage'])}")
            print(f"   ├─ ↑ Отправлено: {self._format_bytes(device['uplink'])}")
            print(f"   └─ ↓ Получено: {self._format_bytes(device['downlink'])}\n")
    
    def print_all_devices(self, data: Dict, show_details: bool = False):
        """
        Красиво напечатать информацию обо всех устройствах
        
        Args:
            data: Данные всех устройств
            show_details: Показывать детальную информацию
        """
        users = data.get('users', [])
        
        total_devices = sum(len(user['devices']) for user in users)
        active_devices = sum(
            sum(1 for d in user['devices'] if d['is_active'])
            for user in users
        )
        
        print(f"\n✅ Найдено пользователей: {len(users)}")
        print(f"   Всего устройств: {total_devices}")
        print(f"   Активных устройств: {active_devices}\n")
        
        for user in users:
            if not user['devices']:
                continue
            
            active_count = sum(1 for d in user['devices'] if d['is_active'])
            
            print(f"   👤 User {user['uid']}:")
            print(f"      Устройств: {len(user['devices'])} (активных: {active_count})")
            
            if show_details:
                for device in user['devices']:
                    status = "🟢" if device['is_active'] else "🔴"
                    traffic = self._format_bytes(device['total_usage'])
                    print(f"      {status} {device['remote_ip']} ({device['client_name']}) - {traffic}")
            else:
                for device in user['devices']:
                    status = "🟢" if device['is_active'] else "🔴"
                    print(f"      {status} {device['remote_ip']} ({device['client_name']})")
            
            print()
    
    def check_multilogin(
        self, 
        node_id: int, 
        user_id: int, 
        max_devices: int = 3
    ) -> bool:
        """
        Проверить мультилогин пользователя
        
        Args:
            node_id: ID ноды
            user_id: ID пользователя
            max_devices: Максимальное количество устройств
            
        Returns:
            True если нарушение обнаружено
        """
        data = self.get_user_devices(node_id, user_id, active_only=True)
        devices = data.get('devices', [])
        active_count = len(devices)
        
        print(f"\n🔍 Проверка мультилогина для пользователя {user_id}")
        print(f"   Активных устройств: {active_count} / {max_devices}")
        
        if active_count > max_devices:
            print(f"\n   ⚠️  НАРУШЕНИЕ: превышен лимит устройств!")
            print(f"\n   Активные устройства:")
            for device in devices:
                print(f"   • {device['remote_ip']} ({device['client_name']})")
                print(f"     Последнее подключение: {self._format_timestamp(device['last_seen'])}")
            return True
        else:
            print(f"\n   ✅ В пределах нормы")
            return False
    
    def analyze_traffic(self, node_id: int, user_id: int, top_n: int = 5):
        """
        Анализ трафика по устройствам
        
        Args:
            node_id: ID ноды
            user_id: ID пользователя
            top_n: Количество топ устройств для показа
        """
        data = self.get_user_devices(node_id, user_id, active_only=False)
        devices = data.get('devices', [])
        
        if not devices:
            print("\n   (нет данных)")
            return
        
        # Сортировка по трафику
        sorted_devices = sorted(
            devices,
            key=lambda d: d['total_usage'],
            reverse=True
        )
        
        total_traffic = sum(d['total_usage'] for d in sorted_devices)
        
        print(f"\n📊 Анализ трафика для пользователя {user_id}")
        print(f"   Общий трафик: {self._format_bytes(total_traffic)}")
        print(f"   Устройств: {len(sorted_devices)}\n")
        
        print(f"   ТОП-{top_n} устройств по трафику:\n")
        
        for idx, device in enumerate(sorted_devices[:top_n], 1):
            percentage = (device['total_usage'] / total_traffic * 100) if total_traffic > 0 else 0
            
            print(f"   {idx}. {device['remote_ip']} ({device['client_name']})")
            print(f"      Трафик: {self._format_bytes(device['total_usage'])} ({percentage:.1f}%)")
            print(f"      ↑ {self._format_bytes(device['uplink'])} | ↓ {self._format_bytes(device['downlink'])}")
            print(f"      Активно: {'🟢 Да' if device['is_active'] else '🔴 Нет'}\n")


def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(
        description='HTTP клиент для Device History API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  %(prog)s user-devices --node-id 1 --user-id 123
  %(prog)s user-devices --node-id 1 --user-id 123 --active-only
  %(prog)s all-devices --node-id 1
  %(prog)s all-devices --node-id 1 --details
  %(prog)s check-multilogin --node-id 1 --user-id 123 --max-devices 3
  %(prog)s analyze-traffic --node-id 1 --user-id 123
        """
    )
    
    parser.add_argument(
        '--url',
        default='http://localhost:8000',
        help='Базовый URL панели (по умолчанию: http://localhost:8000)'
    )
    
    parser.add_argument(
        '--token',
        required=True,
        help='Bearer токен администратора'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Команда')
    
    # Команда: user-devices
    parser_user = subparsers.add_parser(
        'user-devices',
        help='Получить устройства пользователя'
    )
    parser_user.add_argument('--node-id', type=int, required=True, help='ID ноды')
    parser_user.add_argument('--user-id', type=int, required=True, help='ID пользователя')
    parser_user.add_argument('--active-only', action='store_true', help='Только активные')
    parser_user.add_argument('--json', action='store_true', help='Вывести в JSON формате')
    
    # Команда: all-devices
    parser_all = subparsers.add_parser(
        'all-devices',
        help='Получить все устройства'
    )
    parser_all.add_argument('--node-id', type=int, required=True, help='ID ноды')
    parser_all.add_argument('--details', action='store_true', help='Показать детали')
    parser_all.add_argument('--json', action='store_true', help='Вывести в JSON формате')
    
    # Команда: check-multilogin
    parser_check = subparsers.add_parser(
        'check-multilogin',
        help='Проверить мультилогин'
    )
    parser_check.add_argument('--node-id', type=int, required=True, help='ID ноды')
    parser_check.add_argument('--user-id', type=int, required=True, help='ID пользователя')
    parser_check.add_argument('--max-devices', type=int, default=3, help='Макс. устройств')
    
    # Команда: analyze-traffic
    parser_analyze = subparsers.add_parser(
        'analyze-traffic',
        help='Анализ трафика'
    )
    parser_analyze.add_argument('--node-id', type=int, required=True, help='ID ноды')
    parser_analyze.add_argument('--user-id', type=int, required=True, help='ID пользователя')
    parser_analyze.add_argument('--top', type=int, default=5, help='Топ N устройств')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Создать клиент
    client = DeviceAPIClient(args.url, args.token)
    
    # Выполнить команду
    if args.command == 'user-devices':
        data = client.get_user_devices(args.node_id, args.user_id, args.active_only)
        
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            client.print_devices(data)
    
    elif args.command == 'all-devices':
        data = client.get_all_devices(args.node_id)
        
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            client.print_all_devices(data, args.details)
    
    elif args.command == 'check-multilogin':
        violation = client.check_multilogin(
            args.node_id,
            args.user_id,
            args.max_devices
        )
        sys.exit(1 if violation else 0)
    
    elif args.command == 'analyze-traffic':
        client.analyze_traffic(args.node_id, args.user_id, args.top)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Прервано пользователем")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

