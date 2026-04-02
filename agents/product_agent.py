import os
import json
from openai import OpenAI
from message_bus import send_message, get_messages

client = OpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=os.environ["GITHUB_MODELS_TOKEN"],
)


def call_llm(system_prompt: str, user_prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content


def generate_product_spec(idea: str, focus: str, feedback: str | None = None) -> dict:
    """LLM call — generate a full product specification from the startup idea."""
    system_prompt = """You are a senior product manager. Given a startup idea, produce a 
detailed product specification.

Respond ONLY with a valid JSON object. No preamble, no markdown, no explanation.
Schema:
{
  "value_proposition": "<one sentence: what the product does and for whom>",
  "personas": [
    {
      "name": "<persona name>",
      "role": "<who they are>",
      "pain_point": "<specific problem they face>"
    }
  ],
  "features": [
    {
      "name": "<feature name>",
      "description": "<what it does>",
      "priority": <1-5, 1 is highest>
    }
  ],
  "user_stories": [
    {
      "as_a": "<user type>",
      "i_want": "<action>",
      "so_that": "<benefit>"
    }
  ]
}

Rules:
- Exactly 2-3 personas
- Exactly 5 features ranked by priority
- Exactly 3 user stories
- Be specific — avoid generic outputs
- All fields must relate directly to the startup idea provided"""

    user_prompt = f"Startup idea: {idea}\nFocus: {focus}"
    if feedback:
        user_prompt += f"\n\nRevision feedback from CEO: {feedback}\nAddress every point in the feedback."

    return json.loads(call_llm(system_prompt, user_prompt))


def run(feedback: str | None = None) -> dict | None:
    """
    Pick up task (or revision_request) from inbox, generate product spec,
    send it to engineer and marketing, confirm back to CEO.
    """
    messages = get_messages("product")
    if not messages:
        print("[Product] No messages in inbox.")
        return None

    # Take the latest message — either a task or a revision_request
    msg = messages[-1]
    print(f"\n[Product] Received '{msg['message_type']}' from {msg['from_agent'].upper()}")

    idea = msg["payload"].get("idea", "")
    focus = msg["payload"].get("focus", "")
    revision_feedback = msg["payload"].get("feedback") if msg["message_type"] == "revision_request" else feedback

    # --- Generate product spec ---
    print("[Product] Generating product specification...")
    spec = generate_product_spec(idea, focus, revision_feedback)
    print(f"[Product] Spec generated:\n{json.dumps(spec, indent=2)}")

    # --- Send spec to Engineer and Marketing agents ---
    send_message(
        from_agent="product",
        to_agent="engineer",
        message_type="result",
        payload=spec,
        parent_message_id=msg["message_id"],
    )
    send_message(
        from_agent="product",
        to_agent="marketing",
        message_type="result",
        payload=spec,
        parent_message_id=msg["message_id"],
    )
    print("[Product] Spec sent to Engineer and Marketing agents.")

    # --- Confirm back to CEO ---
    send_message(
        from_agent="product",
        to_agent="ceo",
        message_type="confirmation",
        payload={
            "status": "spec_ready",
            "spec": spec,
        },
        parent_message_id=msg["message_id"],
    )
    print("[Product] Confirmation sent to CEO.")

    return spec