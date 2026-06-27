import sys
sys.path.insert(0, "/app")
from sqlalchemy import text
from app.utils.keygen import gen_uuid
from app.db import GetDB

TARGET = "91040b97-0a20-6eac-dfb7-f4b4e56ecf42"

with GetDB() as db:
    rows = db.execute(text(
        "SELECT id, username, `key`, enabled, activated, removed FROM users")).fetchall()
    print("scanning", len(rows), "users")
    match = None
    for r in rows:
        if gen_uuid(r[2]) == TARGET:
            match = r
            break
    if match:
        print(f"BRIDGE USER FOUND: id={match[0]} username={match[1]} "
              f"enabled={match[3]} activated={match[4]} removed={match[5]} key={match[2]}")
        svc = db.execute(text(
            "SELECT us.service_id, s.name FROM users_services us "
            "JOIN services s ON s.id=us.service_id WHERE us.user_id=:u"),
            {"u": match[0]}).fetchall()
        print("  services:", [(s[0], s[1]) for s in svc])
    else:
        print("NO MATCH among panel users -> 91040b97 is an orphan/static bridge id")

    # a real service-1 user uuid for egress comparison
    r = db.execute(text(
        "SELECT u.id,u.username,u.`key` FROM users u JOIN users_services us ON us.user_id=u.id "
        "WHERE us.service_id=1 AND u.enabled=1 AND u.activated=1 AND u.removed=0 LIMIT 1")).fetchone()
    if r:
        print(f"SAMPLE svc1 user id={r[0]} {r[1]} uuid={gen_uuid(r[2])}")
