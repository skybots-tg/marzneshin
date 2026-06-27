-- Find hosts on modified nodes that have host-level reality keys (stale)
SELECT h.id, h.remark, h.sni, h.reality_public_key, h.reality_short_ids, i.node_id, i.tag
FROM hosts h JOIN inbounds i ON h.inbound_id = i.id
WHERE i.node_id IN (17, 34, 36)
  AND h.reality_public_key IS NOT NULL
  AND h.reality_public_key != ''
ORDER BY i.node_id, h.id;

-- Clear host-level reality overrides so they inherit from inbound config
UPDATE hosts h JOIN inbounds i ON h.inbound_id = i.id
SET h.reality_public_key = NULL, h.reality_short_ids = NULL
WHERE i.node_id IN (17, 34, 36)
  AND h.reality_public_key IS NOT NULL
  AND h.reality_public_key != '';

SELECT 'Cleared stale host-level reality keys' as status;

-- Also check hosts on OTHER nodes whose bridges exit through USA
-- These hosts reference inbounds like "RU->US Bridge" on nodes other than 17
-- They should NOT be affected since their inbounds are on other nodes
SELECT h.id, h.remark, i.node_id, i.tag, h.reality_public_key IS NOT NULL as has_host_key
FROM hosts h JOIN inbounds i ON h.inbound_id = i.id  
WHERE i.tag LIKE 'RU->US%'
  AND i.node_id NOT IN (17, 34, 36)
  AND h.is_disabled = 0
LIMIT 10;
