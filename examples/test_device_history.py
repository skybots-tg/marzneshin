#!/usr/bin/env python3
"""
Пример использования Device History API

Этот скрипт демонстрирует:
1. Получение устройств конкретного пользователя
2. Получение всех устройств с ноды
3. Проверку мультилогина
4. Анализ трафика по устройствам
"""

import asyncio
import sys
from typing import Optional
from datetime import datetime

# Предполагается, что скрипт запускается из корня проекта
sys.path.insert(0, '.')

from app import marznode
from app.config import MARZNODE_ADDRESS, MARZNODE_PORT


def format_bytes(bytes_value: int) -> str:
    """Форматировать байты в читаемый вид"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f} PB"


def format_timestamp(timestamp: int) -> str:
    """Форматировать Unix timestamp"""
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')


async def test_fetch_user_devices(node_id: int, user_id: int, active_only: bool = False):
    """
    Тест: получить устройства конкретного пользователя
    """
    print(f"\n{'='*80}")
    print(f"📱 Получение устройств пользователя {user_id} с ноды {node_id}")
    print(f"   Только активные: {active_only}")
    print(f"{'='*80}\n")
    
    node = marznode.nodes.get(node_id)
    if not node:
        print(f"❌ Нода {node_id} не найдена или не подключена")
        return
    
    try:
        response = await node.fetch_user_devices(uid=user_id, active_only=active_only)
        
        print(f"✅ Найдено устройств: {len(response.devices)}")
        print(f"   User ID: {response.uid}\n")
        
        if not response.devices:
            print("   (нет устройств)")
            return
        
        for idx, device in enumerate(response.devices, 1):
            print(f"   Устройство #{idx}:")
            print(f"   ├─ IP адрес: {device.remote_ip}")
            print(f"   ├─ Клиент: {device.client_name}")
            
            if device.user_agent:
                print(f"   ├─ User Agent: {device.user_agent}")
            if device.protocol:
                print(f"   ├─ Протокол: {device.protocol}")
            if device.tls_fingerprint:
                print(f"   ├─ TLS Fingerprint: {device.tls_fingerprint}")
            
            print(f"   ├─ Первое подключение: {format_timestamp(device.first_seen)}")
            print(f"   ├─ Последнее подключение: {format_timestamp(device.last_seen)}")
            print(f"   ├─ Активно: {'🟢 Да' if device.is_active else '🔴 Нет'}")
            print(f"   ├─ Общий трафик: {format_bytes(device.total_usage)}")
            print(f"   ├─ ↑ Отправлено: {format_bytes(device.uplink)}")
            print(f"   └─ ↓ Получено: {format_bytes(device.downlink)}\n")
    
    except Exception as e:
        print(f"❌ Ошибка при получении устройств: {e}")


async def test_fetch_all_devices(node_id: int):
    """
    Тест: получить все устройства с ноды
    """
    print(f"\n{'='*80}")
    print(f"📱 Получение всех устройств с ноды {node_id}")
    print(f"{'='*80}\n")
    
    node = marznode.nodes.get(node_id)
    if not node:
        print(f"❌ Нода {node_id} не найдена или не подключена")
        return
    
    try:
        response = await node.fetch_all_devices()
        
        total_devices = sum(len(user.devices) for user in response.users)
        active_devices = sum(
            sum(1 for d in user.devices if d.is_active)
            for user in response.users
        )
        
        print(f"✅ Найдено пользователей: {len(response.users)}")
        print(f"   Всего устройств: {total_devices}")
        print(f"   Активных устройств: {active_devices}\n")
        
        for user_devices in response.users:
            if not user_devices.devices:
                continue
            
            active_count = sum(1 for d in user_devices.devices if d.is_active)
            
            print(f"   👤 User {user_devices.uid}:")
            print(f"      Устройств: {len(user_devices.devices)} (активных: {active_count})")
            
            for device in user_devices.devices:
                status = "🟢" if device.is_active else "🔴"
                print(f"      {status} {device.remote_ip} ({device.client_name})")
            
            print()
    
    except Exception as e:
        print(f"❌ Ошибка при получении устройств: {e}")


async def test_multilogin_check(node_id: int, user_id: int, max_devices: int = 3):
    """
    Тест: проверка мультилогина
    """
    print(f"\n{'='*80}")
    print(f"🔍 Проверка мультилогина для пользователя {user_id}")
    print(f"   Максимум устройств: {max_devices}")
    print(f"{'='*80}\n")
    
    node = marznode.nodes.get(node_id)
    if not node:
        print(f"❌ Нода {node_id} не найдена или не подключена")
        return
    
    try:
        response = await node.fetch_user_devices(uid=user_id, active_only=True)
        
        active_count = len(response.devices)
        
        print(f"   Активных устройств: {active_count} / {max_devices}")
        
        if active_count > max_devices:
            print(f"\n   ⚠️  НАРУШЕНИЕ: превышен лимит устройств!")
            print(f"\n   Активные устройства:")
            for device in response.devices:
                print(f"   • {device.remote_ip} ({device.client_name})")
                print(f"     Последнее подключение: {format_timestamp(device.last_seen)}")
        else:
            print(f"\n   ✅ В пределах нормы")
        
    except Exception as e:
        print(f"❌ Ошибка при проверке: {e}")


async def test_traffic_analysis(node_id: int, user_id: int):
    """
    Тест: анализ трафика по устройствам
    """
    print(f"\n{'='*80}")
    print(f"📊 Анализ трафика для пользователя {user_id}")
    print(f"{'='*80}\n")
    
    node = marznode.nodes.get(node_id)
    if not node:
        print(f"❌ Нода {node_id} не найдена или не подключена")
        return
    
    try:
        response = await node.fetch_user_devices(uid=user_id, active_only=False)
        
        if not response.devices:
            print("   (нет данных)")
            return
        
        # Сортировка по трафику
        sorted_devices = sorted(
            response.devices,
            key=lambda d: d.total_usage,
            reverse=True
        )
        
        total_traffic = sum(d.total_usage for d in sorted_devices)
        
        print(f"   Общий трафик: {format_bytes(total_traffic)}")
        print(f"   Устройств: {len(sorted_devices)}\n")
        
        print("   ТОП-5 устройств по трафику:\n")
        
        for idx, device in enumerate(sorted_devices[:5], 1):
            percentage = (device.total_usage / total_traffic * 100) if total_traffic > 0 else 0
            
            print(f"   {idx}. {device.remote_ip} ({device.client_name})")
            print(f"      Трафик: {format_bytes(device.total_usage)} ({percentage:.1f}%)")
            print(f"      ↑ {format_bytes(device.uplink)} | ↓ {format_bytes(device.downlink)}")
            print(f"      Активно: {'🟢 Да' if device.is_active else '🔴 Нет'}\n")
    
    except Exception as e:
        print(f"❌ Ошибка при анализе: {e}")


async def test_detect_anomalies(node_id: int, max_ips_per_user: int = 5):
    """
    Тест: обнаружение аномалий
    """
    print(f"\n{'='*80}")
    print(f"🔎 Обнаружение аномалий на ноде {node_id}")
    print(f"   Максимум IP на пользователя: {max_ips_per_user}")
    print(f"{'='*80}\n")
    
    node = marznode.nodes.get(node_id)
    if not node:
        print(f"❌ Нода {node_id} не найдена или не подключена")
        return
    
    try:
        response = await node.fetch_all_devices()
        
        anomalies = []
        
        for user_devices in response.users:
            if not user_devices.devices:
                continue
            
            active_devices = [d for d in user_devices.devices if d.is_active]
            unique_ips = set(d.remote_ip for d in active_devices)
            
            if len(unique_ips) > max_ips_per_user:
                anomalies.append({
                    'uid': user_devices.uid,
                    'ip_count': len(unique_ips),
                    'ips': list(unique_ips)
                })
        
        if not anomalies:
            print("   ✅ Аномалий не обнаружено")
            return
        
        print(f"   ⚠️  Найдено аномалий: {len(anomalies)}\n")
        
        for anomaly in anomalies:
            print(f"   User {anomaly['uid']}:")
            print(f"   └─ Подключен с {anomaly['ip_count']} разных IP:")
            for ip in anomaly['ips']:
                print(f"      • {ip}")
            print()
    
    except Exception as e:
        print(f"❌ Ошибка при обнаружении аномалий: {e}")


async def main():
    """
    Главная функция
    """
    print("\n" + "="*80)
    print("🚀 Device History API - Тестовые сценарии")
    print("="*80)
    
    # Проверка доступности нод
    if not marznode.nodes:
        print("\n❌ Ноды не найдены. Убедитесь, что:")
        print("   1. Marzneshin запущен")
        print("   2. Ноды подключены")
        print("   3. В базе данных есть настроенные ноды\n")
        return
    
    print(f"\n✅ Доступно нод: {len(marznode.nodes)}")
    for node_id in marznode.nodes.keys():
        print(f"   • Нода {node_id}")
    
    # Параметры для тестирования
    # Измените эти значения под вашу конфигурацию
    NODE_ID = 1  # ID ноды для тестирования
    USER_ID = 1  # ID пользователя для тестирования
    
    # Запуск тестов
    await test_fetch_user_devices(NODE_ID, USER_ID, active_only=False)
    
    await test_fetch_user_devices(NODE_ID, USER_ID, active_only=True)
    
    await test_fetch_all_devices(NODE_ID)
    
    await test_multilogin_check(NODE_ID, USER_ID, max_devices=3)
    
    await test_traffic_analysis(NODE_ID, USER_ID)
    
    await test_detect_anomalies(NODE_ID, max_ips_per_user=5)
    
    print("\n" + "="*80)
    print("✅ Все тесты завершены")
    print("="*80 + "\n")


if __name__ == "__main__":
    # Запуск асинхронной главной функции
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Прервано пользователем")
    except Exception as e:
        print(f"\n\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()

