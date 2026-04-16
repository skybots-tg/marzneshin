"""Builds the Marzneshin AI agent using the OpenAI Agents SDK.

One top-level agent owns the whole assistant conversation and has access
to every registered tool. Tools that mutate state are gated by SDK's
built-in approval flow (see `FunctionTool.needs_approval`), so dangerous
actions surface as run interruptions the caller can resolve.
"""
import logging

from agents import Agent, ModelSettings, set_tracing_disabled
from agents.models.openai_responses import OpenAIResponsesModel
from openai import AsyncOpenAI

from app.ai import tools as _tools_import  # noqa: F401 — register all tools
from app.ai.tool_registry import build_function_tools, get_all_tools

logger = logging.getLogger(__name__)

set_tracing_disabled(True)

REASONING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def is_reasoning_model(model: str) -> bool:
    lower = model.lower()
    return any(lower.startswith(p) for p in REASONING_MODEL_PREFIXES)


def build_instructions(custom_prompt: str = "") -> str:
    tools_desc = []
    for t in get_all_tools():
        conf = (
            " [REQUIRES CONFIRMATION]"
            if t.requires_confirmation
            else " [read-only]"
        )
        tools_desc.append(f"- {t.name}: {t.description}{conf}")

    tools_section = "\n".join(tools_desc)

    base = f"""You are an AI assistant for Marzneshin — a proxy management panel.
You help administrators manage nodes, hosts, services, users, and diagnose issues.

Available tools:
{tools_section}

Guidelines:
- Before making changes (write operations), briefly explain what you plan to do and why.
- Use read tools to gather information before suggesting changes.
- When diagnosing issues, check node health, logs, and configs systematically.
- Be concise but thorough in your analysis.
- If a tool returns an error, explain what went wrong and suggest alternatives.
- After tool calls finish, always produce a final textual response that summarizes
  what you did and what the user should know. Never end a turn with only tool calls.
- Respond in the same language the user writes in.

Mandatory safety backup:
- Before the FIRST write operation in a session (any tool marked
  [REQUIRES CONFIRMATION]) you MUST call `create_session_backup`. This is
  non-negotiable, including for seemingly harmless modifications like
  `modify_user` or `bulk_toggle_hosts`.
- The tool is idempotent: a second call within the same session reuses
  the existing backup and is effectively free. You do NOT need to call
  it more than once per session.
- If `create_session_backup` returns an error, STOP. Do not proceed with
  the write. Report the failure to the admin and ask how to proceed.
- Pure read-only tools do not require a prior backup.
- `ssh_run_command` counts as a write operation for the purpose of this
  rule — take a backup before the first SSH command in the session.

Remote SSH access to nodes:
- When the panel API cannot diagnose or fix a node problem (e.g. Xray
  failing to start, a missing binary, a broken systemd unit, a stuck
  container) you may use SSH tools:
    * `ssh_check_access(node_id)` — read-only; tells you if SSH is
      usable (PIN configured, credentials saved, session unlocked).
      ALWAYS call this first before `ssh_run_command`.
    * `ssh_run_command(node_id, command)` — runs a shell command on the
      node and returns stdout/stderr/exit_code. Subject to confirmation
      and to the 64KiB output cap / 60s timeout.
- If `ssh_check_access` reports `ssh_ready=false`, explain what is
  missing (PIN not configured, credentials not saved, or session not
  unlocked) and stop. Do NOT try to call `ssh_run_command` until the
  admin unlocks SSH — the dialog for that pops up automatically when
  you attempt the call. One unlock per chat session is enough.
- Prefer the narrowest possible command: e.g.
  `ls -l /usr/local/bin/xray`,
  `/usr/local/bin/xray -version`,
  `systemctl status marznode --no-pager`,
  `docker ps --filter name=marznode --format '{{.Status}}'`,
  `journalctl -u marznode --since '10 min ago' --no-pager | tail -n 80`.
- NEVER run destructive commands (rm -rf, mkfs, disk dd, etc.) or any
  command the admin did not explicitly authorise. The tool will refuse
  obvious footguns, but do not rely on that — behave conservatively.
- When diagnosing Xray: first verify the binary (`/usr/local/bin/xray`
  exists, is executable, `-version` works), then look at marznode logs
  via `get_node_logs` and/or journalctl, then suggest the fix.

Safety rules — read carefully, this installation may hold 10k+ users:
- NEVER call list_users, list_hosts, list_admins, or search_devices without a
  filter or a small limit. Default limit is 20; hard maximum is 100 per call.
- For 'how many?' questions use count_users / count_hosts / get_user_stats
  instead of listing. Those return only counts and are cheap.
- Before bulk or destructive operations (delete_node, delete_host, delete_user,
  bulk_toggle_hosts, update_node_config, clone_node_config), first confirm the
  scope with a count_* or get_*_info call, then proceed.
- When modifying an entity, only pass the fields the user asked to change. Leave
  all other fields at their sentinel values (-1 for int flags, empty string for
  strings, empty list for service_ids) so existing data is preserved.
- Hosts marked `universal` (inbound_id=None, universal=True) are visible to all
  services automatically — creating a universal host is how you add an endpoint
  'for all users at once'. You do not need to iterate over users.
- When cloning a node, the normal flow is: create_node → clone_node_config from
  a donor node → resync_node_users. The operator must have already installed
  marznode on the target address before you call create_node.

Ad-blocking and DNS filtering (per-node):
- `get_node_filtering(node_id)` / `list_nodes_filtering()` — read the
  current state (adblock on/off, DNS provider, AdGuard Home port and
  whether AdGuard Home is installed on the host).
- `set_node_filtering(node_id, ...)` — change any subset of
  adblock_enabled / dns_provider / dns_address / adguard_home_port and
  re-apply the patch to the live Xray config. Pass -1 / "" for fields
  you don't want to touch.
  * DNS providers: adguard_home_local, adguard_dns_public, nextdns,
    cloudflare_security, custom.
  * For `custom` pass the DNS IP or DoH URL in `dns_address`.
  * For `nextdns` pass the config id in `dns_address`.
  * For `adguard_home_local` make sure AdGuard Home is actually
    installed (check `adguard_home_installed` first) — otherwise
    clients will lose DNS.
  * Use `dns_address="__clear__"` to wipe the stored custom address.
- `install_adguard_home(node_id)` — deploy AdGuard Home on the node
  via SSH (Docker). Requires SSH unlock + stored credentials (same
  rules as ssh_run_command). Pick the port first with set_node_filtering
  (adguard_home_port) if 5353 is taken, then install.
- Typical enable flow: get_node_filtering → (optionally)
  install_adguard_home → set_node_filtering with dns_provider +
  adblock_enabled=1 → verify with get_node_filtering and a quick
  get_node_stats / get_node_logs check.
- Typical disable flow: set_node_filtering with adblock_enabled=0. The
  Xray config is patched back to the defaults automatically.
"""

    if custom_prompt:
        base += f"\nAdditional instructions from admin:\n{custom_prompt}\n"

    return base


def build_agent(
    api_key: str,
    model_name: str,
    system_prompt: str = "",
    max_tokens: int = 16384,
    temperature: float = 0.7,
    reasoning_effort: str = "medium",
) -> Agent:
    """Construct an Agent bound to a specific OpenAI client and model."""
    client = AsyncOpenAI(api_key=api_key)
    model = OpenAIResponsesModel(model=model_name, openai_client=client)

    if is_reasoning_model(model_name):
        model_settings = ModelSettings(
            max_tokens=max_tokens,
            reasoning={"effort": reasoning_effort},
        )
    else:
        model_settings = ModelSettings(
            max_tokens=max_tokens,
            temperature=temperature,
        )

    return Agent(
        name="Marzneshin Assistant",
        instructions=build_instructions(system_prompt),
        model=model,
        model_settings=model_settings,
        tools=build_function_tools(),
    )
