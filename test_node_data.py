#!/usr/bin/env python3
"""
Проверяем ЧТО ИМЕННО приходит от marznode
"""
import asyncio
import sys
import os
sys.path.insert(0, '/app')
os.environ.setdefault('SQLALCHEMY_SILENCE_UBER_WARNING', '1')

async def main():
    # Инициализируем приложение чтобы ноды подключились
    from app.db import GetDB
    from app.db.models import Node
    
    print("\n" + "="*60)
    print("🔍 ТЕСТ: Что приходит от marznode")
    print("="*60)
    
    # Получаем ноды из БД
    with GetDB() as db:
        nodes = db.query(Node).all()
        print(f"\n📊 Нод в базе: {len(nodes)}")
        for n in nodes:
            print(f"  • Node {n.id}: {n.name} ({n.address}) - статус: {n.status}")
    
    if not nodes:
        print("\n❌ Нод нет в базе!")
        return
    
    # Пытаемся подключиться к ноде напрямую
    print(f"\n🔌 Подключаемся к ноде...")
    
    from app.marznode.grpcio import MarzNodeGRPCIO
    from app.marznode.grpclib import MarzNodeGRPCLIB
    
    for node in nodes:
        print(f"\n{'='*60}")
        print(f"Нода: {node.name} ({node.address})")
        print(f"{'='*60}")
        
        try:
            # Пробуем grpcio
            print("\n📡 Пробуем подключиться через grpcio...")
            marznode = MarzNodeGRPCIO(
                address=node.address,
                port=node.port if hasattr(node, 'port') else 62050,
                api_port=node.api_port if hasattr(node, 'api_port') else 62051,
            )
            
            print("⏳ Получаем статистику...")
            stats = await asyncio.wait_for(marznode.fetch_users_stats(), timeout=10)
            
            print(f"✅ Получено записей: {len(stats)}")
            
            if not stats:
                print("⚠️  Статистика пустая")
                continue
            
            # Проверяем первые 5 записей
            print(f"\n📋 Проверяем первые {min(5, len(stats))} записей:\n")
            
            has_remote_ip = False
            
            for i, stat in enumerate(list(stats)[:5]):
                print(f"  Запись #{i+1}:")
                print(f"    uid:         {stat.uid}")
                print(f"    usage:       {stat.usage} bytes")
                
                # Проверяем новые поля
                remote_ip = getattr(stat, 'remote_ip', None)
                uplink = getattr(stat, 'uplink', None)
                downlink = getattr(stat, 'downlink', None)
                client_name = getattr(stat, 'client_name', None)
                user_agent = getattr(stat, 'user_agent', None)
                
                print(f"    remote_ip:   {remote_ip if remote_ip else '❌ НЕТ'}")
                print(f"    uplink:      {uplink if uplink else '❌ НЕТ'}")
                print(f"    downlink:    {downlink if downlink else '❌ НЕТ'}")
                print(f"    client_name: {client_name if client_name else '❌ НЕТ'}")
                print(f"    user_agent:  {user_agent if user_agent else '❌ НЕТ'}")
                print()
                
                if remote_ip:
                    has_remote_ip = True
            
            # Статистика
            total_with_ip = sum(1 for s in stats if getattr(s, 'remote_ip', None))
            
            print(f"\n📊 Статистика:")
            print(f"  Всего записей:      {len(stats)}")
            print(f"  С remote_ip:        {total_with_ip}")
            print(f"  Без remote_ip:      {len(stats) - total_with_ip}")
            
            if has_remote_ip:
                print(f"\n✅ ХОРОШО: Marznode ОТПРАВЛЯЕТ remote_ip!")
                print(f"   → Device tracking должен работать")
            else:
                print(f"\n❌ ПРОБЛЕМА: Marznode НЕ отправляет remote_ip")
                print(f"   → Это СТАРАЯ версия marznode")
                print(f"   → Нужно обновить marznode с новым protobuf")
            
        except asyncio.TimeoutError:
            print("❌ Timeout - нода не отвечает")
        except Exception as e:
            print(f"❌ Ошибка: {type(e).__name__}: {e}")
    
    print("\n" + "="*60)
    print("🏁 ВЫВОД:")
    print("="*60)
    print("""
Если видишь "❌ НЕТ" у remote_ip:
  → Проблема в MARZNODE (не в marzneshin)
  → Marznode использует старый protobuf без новых полей
  → Решение: обновить marznode

Если видишь IP адреса:
  → Marznode работает правильно
  → Проблема может быть в обработке на стороне marzneshin
  → Нужно смотреть логи marzneshin
""")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())

