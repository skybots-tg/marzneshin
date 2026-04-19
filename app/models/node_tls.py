from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NodeTLSProvisioningResponse(BaseModel):
    """Public view of a node's TLS provisioning state.

    `cert_issued_at` / `cert_expires_at` are NULL until the very first
    successful Caddy run. `domain` is canonicalized to lowercase by the
    provisioner.
    """
    node_id: int
    domain: str
    landing_template: str
    grpc_service_name: str
    uds_path: str
    contact_email: str
    cert_issued_at: datetime | None
    cert_expires_at: datetime | None
    last_renew_attempt_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
