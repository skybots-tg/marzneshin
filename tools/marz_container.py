"""Which docker container on a node is *the* marznode.

Shell, not Python: the snippet runs on the node and leaves the name in ``$c``.

``grep -i marz | head -1`` was enough while every node ran one container. EE-1
also runs ``marznode2`` (the IHC web gateway, ``/var/lib/marznode2``), and on
2026-11-01 a front change wrote node 48's config to ``/var/lib/marznode`` but
restarted ``marznode2`` -- node 48 kept dialling the old, banning ``dest``. The
container that mounts ``/var/lib/marznode`` is the one whose config we edit.
"""

MARZ_CONTAINER_SH = r'''c=""
for n in $(docker ps --format '{{.Names}}' | grep -i marz); do
  if docker inspect -f '{{range .Mounts}}{{println .Source}}{{end}}' "$n" | grep -qx /var/lib/marznode; then c=$n; break; fi
done
[ -n "$c" ] || c=$(docker ps --format '{{.Names}}' | grep -i marz | head -1)
'''
