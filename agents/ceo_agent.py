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


def review_qa_report(qa_report: dict) -> dict:
    """LLM call #3 — reason about QA verdict and decide next action."""
    system_prompt = """You are a CEO reviewing a QA report.
The QA agent has already made the pass/fail decision. Your job is to respect it.

Rules:
- If both html_review and copy_review verdicts are 'pass', you MUST return verdict: 'accept'
- Only return verdict: 'revise' if at least one verdict is 'fail'
- Do not invent new issues beyond what QA flagged as failures
- Minor suggestions from QA do not count as failures

Respond ONLY with a valid JSON object:
{
  "verdict": "accept" or "revise",
  "engineer_feedback": "<only if html_review verdict was fail, else empty string>",
  "marketing_feedback": "<only if copy_review verdict was fail, else empty string>",
  "reasoning": "<brief explanation>"
}"""

    user_prompt = f"QA Report:\n{json.dumps(qa_report, indent=2)}"
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


def send_qa_task(spec: dict, html: str, pr_url: str, folder_name: str, marketing_copy: dict) -> str:
    """Send task to QA agent. Returns message_id."""
    print("\n[CEO] Forwarding Engineer and Marketing output to QA agent...")
    msg = send_message(
        from_agent="ceo",
        to_agent="qa",
        message_type="task",
        payload={
            "spec": spec,
            "html": html,
            "pr_url": pr_url,
            "folder_name": folder_name,
            "marketing_copy": marketing_copy,
        },
    )
    return msg["message_id"]


def handle_qa_report(qa_report: dict, spec: dict, parent_id: str) -> dict:
    """
    LLM call #3 — reason about QA verdict.
    Returns dict with verdict and any revision instructions.
    """
    print("\n[CEO] Reviewing QA report...")
    decision = review_qa_report(qa_report)
    print(f"[CEO] QA decision: {decision['verdict']}")
    print(f"[CEO] Reasoning: {decision['reasoning']}")

    if decision["verdict"] == "accept":
        print("[CEO] QA output accepted. Forwarding PR link to Marketing.")
        return {"verdict": "accept"}

    # Build revision requests
    result = {"verdict": "revise"}

    if decision["engineer_feedback"]:
        print(f"[CEO] Requesting Engineer revision: {decision['engineer_feedback']}")
        send_message(
            from_agent="ceo",
            to_agent="engineer",
            message_type="revision_request",
            payload={
                "feedback": decision["engineer_feedback"],
                "spec": spec,
            },
            parent_message_id=parent_id,
        )
        result["engineer_feedback"] = decision["engineer_feedback"]

    if decision["marketing_feedback"]:
        print(f"[CEO] Requesting Marketing revision: {decision['marketing_feedback']}")
        send_message(
            from_agent="ceo",
            to_agent="marketing",
            message_type="revision_request",
            payload={"feedback": decision["marketing_feedback"]},
            parent_message_id=parent_id,
        )
        result["marketing_feedback"] = decision["marketing_feedback"]

    return result


def forward_pr_to_marketing(pr_url: str, startup_name: str) -> None:
    """Forward PR URL to Marketing agent so it can post to Slack."""
    print("\n[CEO] Forwarding PR link to Marketing agent...")
    send_message(
        from_agent="ceo",
        to_agent="marketing",
        message_type="task",
        payload={
            "pr_url": pr_url,
            "startup_name": startup_name,
        },
    )