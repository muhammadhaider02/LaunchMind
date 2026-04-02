import os
import json
import requests
from openai import OpenAI
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from message_bus import send_message, get_messages

client = OpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=os.environ["GITHUB_MODELS_TOKEN"],
)

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SENDGRID_API_KEY = os.environ["SENDGRID_API_KEY"]
SENDGRID_FROM_EMAIL = os.environ["SENDGRID_FROM_EMAIL"]
MARKETING_TEST_EMAIL = os.environ["MARKETING_TEST_EMAIL"]
SLACK_CHANNEL = "#launches"
SENDER_NAME = "Haider Akbar"


def call_llm(system_prompt: str, user_prompt: str) -> dict:
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def generate_marketing_copy(spec: dict, feedback: str | None = None) -> dict:
    """LLM call — generate all marketing content from the product spec."""
    system_prompt = f"""You are a growth marketer. Given a product specification, generate marketing content.

Respond ONLY with a valid JSON object:
{{
  "tagline": "<punchy tagline under 10 words>",
  "landing_page_description": "<2-3 sentence product description for a landing page>",
  "cold_email": {{
    "subject": "<compelling email subject line>",
    "body": "<cold outreach email body to a potential early user or investor, 150-200 words. End with 'Best regards,\\n{SENDER_NAME}'>"
  }},
  "social_posts": {{
    "twitter": "<tweet under 280 characters, include relevant hashtags>",
    "linkedin": "<LinkedIn post, 2-3 short paragraphs, professional tone>",
    "instagram": "<Instagram caption with emojis and hashtags>"
  }}
}}

Rules:
- Tagline must be specific to this product, not generic
- Cold email must have a clear call to action
- Cold email must be signed off with 'Best regards,\\n{SENDER_NAME}' — no placeholders
- All content must relate directly to the product spec provided"""

    user_prompt = f"Product spec:\n{json.dumps(spec, indent=2)}"
    if feedback:
        user_prompt += f"\n\nRevision feedback from CEO: {feedback}\nAddress every point."

    return call_llm(system_prompt, user_prompt)


def send_email(subject: str, body: str) -> None:
    """Send cold outreach email via SendGrid."""
    print(f"[Marketing] Sending email to {MARKETING_TEST_EMAIL}...")
    message = Mail(
        from_email=SENDGRID_FROM_EMAIL,
        to_emails=MARKETING_TEST_EMAIL,
        subject=subject,
        html_content=f"<p>{body.replace(chr(10), '<br>')}</p>",
    )
    sg = SendGridAPIClient(SENDGRID_API_KEY)
    sg.send(message)
    print(f"[Marketing] Email sent.")


def post_to_slack(startup_name: str, tagline: str, description: str, pr_url: str) -> None:
    """Post launch announcement to #launches using Block Kit."""
    print(f"[Marketing] Posting to Slack {SLACK_CHANNEL}...")
    payload = {
        "channel": SLACK_CHANNEL,
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"New Launch: {startup_name}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{tagline}*\n\n{description}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*GitHub PR:* <{pr_url}|View PR>"},
                    {"type": "mrkdwn", "text": "*Status:* QA Approved"},
                ],
            },
            {
                "type": "divider",
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Posted by LaunchMind Marketing Agent",
                    }
                ],
            },
        ],
    }
    r = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json=payload,
    )
    data = r.json()
    if not data.get("ok"):
        print(f"[Marketing] Slack error: {data.get('error')}")
    else:
        print(f"[Marketing] Slack message posted.")


def run(feedback: str | None = None) -> dict | None:
    """
    Phase 1 (parallel with Engineer): pick up spec, generate copy, send email.
    Phase 2 (after CEO forwards PR link post-QA approval): post to Slack, report to CEO.
    """
    messages = get_messages("marketing")
    if not messages:
        print("[Marketing] No messages in inbox.")
        return None

    spec_msg = None
    pr_msg = None
    revision_msg = None

    for msg in messages:
        if msg["from_agent"] == "product" and msg["message_type"] == "result":
            spec_msg = msg
        if msg["from_agent"] == "ceo" and msg["message_type"] == "task":
            pr_msg = msg
        if msg["from_agent"] == "ceo" and msg["message_type"] == "revision_request":
            revision_msg = msg

    if not spec_msg:
        print("[Marketing] No product spec found in inbox.")
        return None

    spec = spec_msg["payload"]
    revision_feedback = revision_msg["payload"].get("feedback") if revision_msg else feedback
    print(f"\n[Marketing] Received product spec from PRODUCT.")

    # --- Phase 1: Generate copy and send email ---
    print("[Marketing] Generating marketing copy...")
    copy = generate_marketing_copy(spec, revision_feedback)
    print(f"[Marketing] Copy generated.")

    print("[Marketing] Sending cold outreach email...")
    send_email(copy["cold_email"]["subject"], copy["cold_email"]["body"])

    # Post to Slack only if CEO has already forwarded the PR link (post-QA approval)
    if pr_msg:
        pr_url = pr_msg["payload"]["pr_url"]
        startup_name = pr_msg["payload"].get("startup_name", "Startup")
        post_to_slack(startup_name, copy["tagline"], copy["landing_page_description"], pr_url)
    else:
        print("[Marketing] PR link not yet available. Slack post deferred until QA approves.")

    # --- Report all copy back to CEO ---
    result = {
        "copy": copy,
        "email_sent": True,
        "slack_posted": bool(pr_msg),
    }
    send_message(
        from_agent="marketing",
        to_agent="ceo",
        message_type="result",
        payload=result,
        parent_message_id=spec_msg["message_id"],
    )
    print("[Marketing] All copy sent to CEO.")
    return result


def post_slack_with_pr(pr_url: str, startup_name: str, copy: dict) -> None:
    """Called by main.py after QA approves, if Marketing ran before PR was available."""
    post_to_slack(startup_name, copy["tagline"], copy["landing_page_description"], pr_url)