import os
import json
from openai import OpenAI
from message_bus import send_message, get_messages

client = OpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=os.environ["GITHUB_MODELS_TOKEN"],
)

MAX_RETRIES = 2


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


def decompose_idea(idea: str) -> dict:
    """LLM call #1 — break the startup idea into tasks for each sub-agent."""
    system_prompt = """You are the CEO of a startup. You receive a startup idea and break it 
into specific tasks for three agents: product, engineer, and marketing.

Respond ONLY with a valid JSON object. No preamble, no markdown, no explanation.
Schema:
{
  "product": {
    "idea": "<startup idea>",
    "focus": "<what the product agent should focus on>"
  },
  "engineer": {
    "focus": "<what the engineer agent should build>"
  },
  "marketing": {
    "focus": "<what the marketing agent should produce>"
  }
}"""

    user_prompt = f"Startup idea: {idea}"
    return json.loads(call_llm(system_prompt, user_prompt))


def review_output(agent_name: str, output: dict) -> dict:
    """LLM call #2 — review an agent's output and decide accept or revise."""
    system_prompt = """You are an extremely strict CEO reviewing output from your product agent.
You MUST request revision if ANY of the following are true:
- The startup idea in the spec is vague or could apply to any generic app
- Personas have generic names like 'User' or roles that are not specific enough
- Features are not directly tied to the specific startup idea
- Value proposition does not mention a specific target audience and a specific problem
- Any field feels copy-pasted or generic rather than tailored to this exact idea

Only accept if every field is highly specific, concrete, and clearly tied to the startup idea.
When in doubt, request revision.

Respond ONLY with a valid JSON object. No preamble, no markdown.
Schema:
{
  "verdict": "accept" or "revise",
  "feedback": "<specific, actionable feedback if verdict is revise, else empty string>"
}"""

    user_prompt = f"Agent: {agent_name}\nOutput:\n{json.dumps(output, indent=2)}"
    return json.loads(call_llm(system_prompt, user_prompt))


def run(idea: str) -> dict:
    print(f"\n[CEO] Received idea: {idea}")

    # --- Step 1: Decompose idea into tasks ---
    print("[CEO] Decomposing idea into tasks...")
    tasks = decompose_idea(idea)
    print(f"[CEO] Tasks generated:\n{json.dumps(tasks, indent=2)}")

    # --- Step 2: Send task to Product agent ---
    task_msg = send_message(
        from_agent="ceo",
        to_agent="product",
        message_type="task",
        payload=tasks["product"],
    )
    print(f"[CEO] Task sent to Product agent.")

    return {
        "tasks": tasks,
        "task_message_id": task_msg["message_id"],
    }


def review_and_proceed(product_output: dict, parent_id: str) -> dict:
    """
    Called after Product agent responds.
    Reviews output — accepts or sends revision_request.
    Returns final accepted product spec.
    """
    for attempt in range(MAX_RETRIES + 1):
        print(f"\n[CEO] Reviewing Product agent output (attempt {attempt + 1})...")
        review = review_output("product", product_output)
        print(f"[CEO] Review verdict: {review['verdict']}")

        if review["verdict"] == "accept":
            print("[CEO] Product spec accepted.")
            send_message(
                from_agent="ceo",
                to_agent="product",
                message_type="confirmation",
                payload={"status": "accepted"},
                parent_message_id=parent_id,
            )
            return product_output

        if attempt < MAX_RETRIES:
            print(f"[CEO] Requesting revision: {review['feedback']}")
            send_message(
                from_agent="ceo",
                to_agent="product",
                message_type="revision_request",
                payload={"feedback": review["feedback"]},
                parent_message_id=parent_id,
            )
            return {"needs_revision": True, "feedback": review["feedback"]}

    # Max retries hit — accept whatever we have and move on
    print("[CEO] Max retries reached. Accepting product spec as-is.")
    return product_output