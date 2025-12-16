#!/usr/bin/env python3
"""
Скрипт для проверки работы device tracking
Запускать на сервере в контейнере marzneshin
"""
import asyncio
import sys
sys.path.insert(0, '/app')

from app import marznode
from app.db import GetDB
from app.db.models import UserDevice, UserDeviceIP
from sqlalchemy import func


async def check_marznode_data():
    """Проверяем, что приходит от marznode"""
    print("=" * 60)
    print("🔍 Проверка данных от marznode")
    print("=" * 60)
    
    if not marznode.nodes:
        print("❌ Нет подключенных нод!")
        return
    
    for node_id, node in marznode.nodes.items():
        print(f"\n📡 Node ID: {node_id}")
        print(f"   Адрес: {node.address}")
        
        try:
            stats = await asyncio.wait_for(node.fetch_users_stats(), timeout=10)
            
            if not stats:
                print("   ⚠️  Нет статистики")
                continue
            
            print(f"   ✓ Получено записей: {len(stats)}")
            
            # Проверяем первые 3 записи
            for i, stat in enumerate(list(stats)[:3]):
                print(f"\n   Запись #{i+1}:")
                print(f"      uid: {stat.uid}")
                print(f"      usage: {stat.usage}")
                print(f"      remote_ip: {getattr(stat, 'remote_ip', '❌ НЕТ')}")
                print(f"      uplink: {getattr(stat, 'uplink', '❌ НЕТ')}")
                print(f"      downlink: {getattr(stat, 'downlink', '❌ НЕТ')}")
                print(f"      client_name: {getattr(stat, 'client_name', '❌ НЕТ')}")
                print(f"      user_agent: {getattr(stat, 'user_agent', '❌ НЕТ')}")
            
            # Проверяем, есть ли хотя бы один с remote_ip
            has_remote_ip = any(getattr(s, 'remote_ip', None) for s in stats)
            
            if has_remote_ip:
                print(f"\n   ✅ Marznode отправляет remote_ip!")
            else:
                print(f"\n   ❌ Marznode НЕ отправляет remote_ip")
                print(f"   → Нужно обновить marznode!")
                
        except asyncio.TimeoutError:
            print("   ❌ Timeout при получении статистики")
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")


def check_database():
    """Проверяем базу данных"""
    print("\n" + "=" * 60)
    print("💾 Проверка базы данных")
    print("=" * 60)
    
    with GetDB() as db:
        # Проверяем таблицы
        from sqlalchemy import inspect
        inspector = inspect(db.bind)
        tables = inspector.get_table_names()
        
        print("\n📊 Таблицы device tracking:")
        for table in ['user_devices', 'user_device_ips', 'user_device_traffic']:
            exists = table in tables
            status = "✓" if exists else "❌"
            print(f"   {status} {table}")
            
            if exists:
                if table == 'user_devices':
                    count = db.query(func.count(UserDevice.id)).scalar()
                    print(f"      Записей: {count}")
                    
                    if count > 0:
                        # Показываем последние устройства
                        devices = db.query(UserDevice).order_by(UserDevice.last_seen_at.desc()).limit(5).all()
                        print("\n      Последние устройства:")
                        for d in devices:
                            print(f"        • Device ID {d.id}: user={d.user_id}, client={d.client_name or 'unknown'}, last_seen={d.last_seen_at}")
                
                elif table == 'user_device_ips':
                    count = db.query(func.count(UserDeviceIP.id)).scalar()
                    print(f"      Записей: {count}")
                    
                    if count > 0:
                        ips = db.query(UserDeviceIP).order_by(UserDeviceIP.last_seen_at.desc()).limit(5).all()
                        print("\n      Последние IP:")
                        for ip in ips:
                            print(f"        • {ip.ip}: device_id={ip.device_id}, connects={ip.connect_count}, last_seen={ip.last_seen_at}")


async def main():
    print("\n🔧 Device Tracking Diagnostic Tool\n")
    
    # 1. Проверяем marznode
    await check_marznode_data()
    
    # 2. Проверяем БД
    check_database()
    
    print("\n" + "=" * 60)
    print("📋 Итоги:")
    print("=" * 60)
    print("""
Если marznode НЕ отправляет remote_ip:
  → Marznode нужно обновить!
  → Обновленная версия protobuf должна быть в marznode
  → Marznode должен парсить логи и отправлять IP адреса

Если БД пустая, но marznode отправляет данные:
  → Проверь логи: docker compose logs marzneshin | grep -i device
  → Возможно ошибка в track_user_connection
""")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

