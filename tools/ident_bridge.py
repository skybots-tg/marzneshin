import sys
sys.path.insert(0, "/app")
from app.utils.keygen import gen_uuid
from app.config.env import AUTH_GENERATION_ALGORITHM

print("ALGO:", AUTH_GENERATION_ALGORITHM)
print("user4 test_ru_ee_bridge key=0b20691e7a4428cf6a79d888699ba3ca ->", gen_uuid("0b20691e7a4428cf6a79d888699ba3ca"))

from app.db import GetDB
from app.db.models import User
with GetDB() as db:
    # pick a few active service-1 users
    rows = db.execute(
        "SELECT u.id,u.username,u.`key` FROM users u "
        "JOIN users_services us ON us.user_id=u.id "
        "WHERE us.service_id=1 AND u.enabled=1 AND u.activated=1 AND u.removed=0 LIMIT 3"
    ).fetchall()
    for r in rows:
        print(f"svc1 user id={r[0]} {r[1]} -> uuid={gen_uuid(r[2])}")
