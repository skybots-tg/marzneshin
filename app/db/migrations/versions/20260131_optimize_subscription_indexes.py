"""Add critical indexes for subscription performance

Revision ID: optimize_subscription
Revises: 20241219_add_device_limit
Create Date: 2026-01-31

This migration adds indexes that dramatically improve subscription endpoint performance.
The main bottleneck was N+1 queries and missing indexes on frequently filtered columns.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "optimize_subscription"
down_revision = "20241219_add_device_limit"
branch_labels = None
depends_on = None


def index_exists(connection, table_name, index_name):
    """Check if index already exists."""
    inspector = inspect(connection)
    indexes = inspector.get_indexes(table_name)
    return any(idx['name'] == index_name for idx in indexes)


def safe_create_index(connection, index_name, table_name, columns):
    """Create index only if it doesn't exist."""
    if not index_exists(connection, table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=False)


def safe_drop_index(connection, index_name, table_name):
    """Drop index only if it exists."""
    if index_exists(connection, table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    connection = op.get_bind()
    
    # Critical indexes for node_user_usages (grows very fast!)
    safe_create_index(connection, "ix_node_user_usages_user_id", "node_user_usages", ["user_id"])
    safe_create_index(connection, "ix_node_user_usages_node_id", "node_user_usages", ["node_id"])
    safe_create_index(connection, "ix_node_user_usages_created_at", "node_user_usages", ["created_at"])
    
    # Composite index for the most common query pattern
    safe_create_index(connection, "ix_node_user_usages_lookup", "node_user_usages", 
                      ["node_id", "created_at", "user_id"])
    
    # Indexes for users table (frequently filtered columns)
    safe_create_index(connection, "ix_users_admin_id", "users", ["admin_id"])
    safe_create_index(connection, "ix_users_enabled", "users", ["enabled"])
    safe_create_index(connection, "ix_users_activated", "users", ["activated"])
    safe_create_index(connection, "ix_users_removed", "users", ["removed"])
    
    # Composite index for get_node_users query
    safe_create_index(connection, "ix_users_active_lookup", "users", ["activated", "removed"])
    
    # Indexes for hosts table (used in subscription generation)
    safe_create_index(connection, "ix_hosts_inbound_id", "hosts", ["inbound_id"])
    safe_create_index(connection, "ix_hosts_is_disabled", "hosts", ["is_disabled"])
    safe_create_index(connection, "ix_hosts_universal", "hosts", ["universal"])
    
    # Composite index for host lookup
    safe_create_index(connection, "ix_hosts_lookup", "hosts", ["is_disabled", "inbound_id"])
    
    # Indexes for junction tables (these are critical for JOIN performance!)
    safe_create_index(connection, "ix_users_services_user_id", "users_services", ["user_id"])
    safe_create_index(connection, "ix_users_services_service_id", "users_services", ["service_id"])
    safe_create_index(connection, "ix_inbounds_services_inbound_id", "inbounds_services", ["inbound_id"])
    safe_create_index(connection, "ix_inbounds_services_service_id", "inbounds_services", ["service_id"])
    
    # Index for hosts_services junction table
    safe_create_index(connection, "ix_hosts_services_host_id", "hosts_services", ["host_id"])
    safe_create_index(connection, "ix_hosts_services_service_id", "hosts_services", ["service_id"])


def downgrade() -> None:
    connection = op.get_bind()
    
    # Remove indexes in reverse order
    safe_drop_index(connection, "ix_hosts_services_service_id", "hosts_services")
    safe_drop_index(connection, "ix_hosts_services_host_id", "hosts_services")
    safe_drop_index(connection, "ix_inbounds_services_service_id", "inbounds_services")
    safe_drop_index(connection, "ix_inbounds_services_inbound_id", "inbounds_services")
    safe_drop_index(connection, "ix_users_services_service_id", "users_services")
    safe_drop_index(connection, "ix_users_services_user_id", "users_services")
    safe_drop_index(connection, "ix_hosts_lookup", "hosts")
    safe_drop_index(connection, "ix_hosts_universal", "hosts")
    safe_drop_index(connection, "ix_hosts_is_disabled", "hosts")
    safe_drop_index(connection, "ix_hosts_inbound_id", "hosts")
    safe_drop_index(connection, "ix_users_active_lookup", "users")
    safe_drop_index(connection, "ix_users_removed", "users")
    safe_drop_index(connection, "ix_users_activated", "users")
    safe_drop_index(connection, "ix_users_enabled", "users")
    safe_drop_index(connection, "ix_users_admin_id", "users")
    safe_drop_index(connection, "ix_node_user_usages_lookup", "node_user_usages")
    safe_drop_index(connection, "ix_node_user_usages_created_at", "node_user_usages")
    safe_drop_index(connection, "ix_node_user_usages_node_id", "node_user_usages")
    safe_drop_index(connection, "ix_node_user_usages_user_id", "node_user_usages")
