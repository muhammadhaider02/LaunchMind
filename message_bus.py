import uuid
from datetime import datetime, timezone


# Shared message bus — one inbox per agent
_bus: dict[str, list[dict]] = {
    "ceo": [],
    "product": [],
    "engineer": [],
    "marketing": [],
    "qa": [],
}


def send_message(
    from_agent: str,
    to_agent: str,
    message_type: str,
    payload: dict,
    parent_message_id: str | None = None,
) -> dict:
    """Build a structured message and drop it in the recipient's inbox."""
    message = {
        "message_id": str(uuid.uuid4()),
        "from_agent": from_agent,
        "to_agent": to_agent,
        "message_type": message_type,  # task | result | revision_request | confirmation
        "payload": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if parent_message_id:
        message["parent_message_id"] = parent_message_id

    _bus[to_agent].append(message)
    _log(message)
    return message


def get_messages(agent: str) -> list[dict]:
    """Return and clear all pending messages for an agent."""
    messages = _bus[agent].copy()
    _bus[agent].clear()
    return messages


def get_history() -> dict[str, list[dict]]:
    """Return the full message log (all agents, all messages ever sent)."""
    return _log_history


def _log(message: dict) -> None:
    """Append to the global log so full history is always available."""
    _log_history.setdefault(message["from_agent"], []).append(message)
    print(
        f"[{message['timestamp']}] "
        f"{message['from_agent'].upper()} → {message['to_agent'].upper()} "
        f"| type: {message['message_type']} "
        f"| id: {message['message_id']}"
    )


# Full message history — never cleared, used for debugging
_log_history: dict[str, list[dict]] = {}