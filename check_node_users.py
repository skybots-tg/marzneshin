"""
Скрипт для проверки, какие пользователи попадают на конкретную ноду
и почему пользователь попадает или не попадает на ноду.

Использование:
    python check_node_users.py <node_id> [user_id]
    
Примеры:
    # Показать всех пользователей на ноде 12
    python check_node_users.py 12
    
    # Проверить, попадает ли пользователь 5 на ноду 12
    python check_node_users.py 12 5
"""

import sys
from app.db import GetDB
from app.db import crud
from app.db.models import User, Service, Inbound, Node


def check_user_on_node(node_id: int, user_id: int = None):
    """Проверяет, какие пользователи попадают на ноду"""
    with GetDB() as db:
        # Проверяем существование ноды
        node = crud.get_node_by_id(db, node_id)
        if not node:
            print(f"❌ Нода {node_id} не найдена")
            return
        
        print(f"📡 Нода: {node.name} (ID: {node.id})")
        print(f"   Адрес: {node.address}:{node.port}")
        print(f"   Usage coefficient: {node.usage_coefficient}")
        print()
        
        # Получаем все инбаунды ноды
        inbounds = db.query(Inbound).filter(Inbound.node_id == node_id).all()
        print(f"🔌 Инбаунды на ноде ({len(inbounds)}):")
        for inbound in inbounds:
            services = inbound.services
            print(f"   - {inbound.tag} (ID: {inbound.id}, протокол: {inbound.protocol})")
            print(f"     Сервисы: {[s.name for s in services]}")
        print()
        
        if user_id:
            # Проверяем конкретного пользователя
            user = crud.get_user_by_id(db, user_id)
            if not user:
                print(f"❌ Пользователь {user_id} не найден")
                return
            
            print(f"👤 Пользователь: {user.username} (ID: {user.id})")
            print(f"   Activated: {user.activated}")
            print(f"   Enabled: {user.enabled}")
            print(f"   Removed: {user.removed}")
            print(f"   Data limit reached: {user.data_limit_reached}")
            print()
            
            # Проверяем связи
            user_services = user.services
            print(f"📋 Сервисы пользователя ({len(user_services)}):")
            for service in user_services:
                print(f"   - {service.name} (ID: {service.id})")
                service_inbounds = [inb for inb in service.inbounds if inb.node_id == node_id]
                if service_inbounds:
                    print(f"     ✅ Инбаунды на ноде {node_id}: {[inb.tag for inb in service_inbounds]}")
                else:
                    print(f"     ❌ Нет инбаундов на ноде {node_id}")
            print()
            
            # Проверяем через get_node_users
            node_users = crud.get_node_users(db, node_id)
            user_found = any(rel[0] == user_id for rel in node_users)
            
            if user_found:
                print(f"✅ Пользователь {user.username} ПОПАДАЕТ на ноду {node.name}")
                print()
                print("Причина:")
                print("   - Пользователь активирован (activated=True)")
                if node.usage_coefficient > 0:
                    print("   - Лимит трафика не достигнут (data_limit_reached=False)")
                print("   - У пользователя есть сервис, связанный с инбаундом на этой ноде")
            else:
                print(f"❌ Пользователь {user.username} НЕ попадает на ноду {node.name}")
                print()
                print("Возможные причины:")
                if not user.activated:
                    print("   ❌ Пользователь не активирован (activated=False)")
                if node.usage_coefficient > 0 and user.data_limit_reached:
                    print("   ❌ Лимит трафика достигнут (data_limit_reached=True)")
                
                # Проверяем связи
                user_has_service_with_node_inbound = False
                for service in user.services:
                    for inbound in service.inbounds:
                        if inbound.node_id == node_id:
                            user_has_service_with_node_inbound = True
                            break
                
                if not user_has_service_with_node_inbound:
                    print("   ❌ У пользователя нет сервиса, связанного с инбаундом на этой ноде")
                    print()
                    print("   Что нужно сделать:")
                    print("   1. Убедитесь, что у пользователя есть сервис")
                    print("   2. Убедитесь, что у этого сервиса есть инбаунд")
                    print("   3. Убедитесь, что этот инбаунд привязан к нужной ноде")
        else:
            # Показываем всех пользователей на ноде
            node_users = crud.get_node_users(db, node_id)
            print(f"👥 Пользователи на ноде ({len(node_users)}):")
            print()
            
            if not node_users:
                print("   Нет пользователей на этой ноде")
                print()
                print("Возможные причины:")
                print("   - Нет инбаундов на ноде")
                print("   - Нет сервисов, связанных с инбаундами ноды")
                print("   - Нет пользователей, связанных с этими сервисами")
                print("   - Все пользователи не активированы или достигли лимита")
            else:
                for rel in node_users:
                    user_id, username, key, inbound = rel
                    user = crud.get_user_by_id(db, user_id)
                    print(f"   - {username} (ID: {user_id})")
                    print(f"     Инбаунд: {inbound.tag}")
                    if user:
                        print(f"     Activated: {user.activated}, Limit reached: {user.data_limit_reached}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    try:
        node_id = int(sys.argv[1])
        user_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
        check_user_on_node(node_id, user_id)
    except ValueError:
        print("❌ Ошибка: node_id и user_id должны быть числами")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
