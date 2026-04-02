import json
import sys
import os
import threading
import requests

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "agents"))

from message_bus import get_history, send_message
import ceo_agent
import product_agent
import engineer_agent
import marketing_agent
import qa_agent

QA_MAX_RETRIES = 2


def run_pipeline(idea: str):
    print("\n" + "=" * 60)
    print(f"  LAUNCHMIND PIPELINE STARTING")
    print(f"  Idea: {idea}")
    print("=" * 60)

    # --- Step 1: CEO decomposes idea and tasks Product agent ---
    ceo_result = ceo_agent.run(idea)
    task_message_id = ceo_result["task_message_id"]

    # --- Step 2: Product agent generates spec ---
    product_spec = product_agent.run()
    if not product_spec:
        print("\n[MAIN] Product agent returned nothing. Aborting.")
        return

    # --- Step 3: CEO reviews product spec (feedback loop) ---
    review_result = ceo_agent.review_and_proceed(product_spec, task_message_id)

    if review_result.get("needs_revision"):
        print(f"\n[MAIN] CEO requested revision. Re-running Product agent...")
        product_spec = product_agent.run(feedback=review_result["feedback"])
        if not product_spec:
            print("\n[MAIN] Product agent returned nothing on revision. Aborting.")
            return
        review_result = ceo_agent.review_and_proceed(product_spec, task_message_id)

    print("\n[MAIN] Product spec accepted. Running Engineer and Marketing in parallel...")

    # --- Step 4: Engineer and Marketing run in parallel ---
    engineer_result = {}
    marketing_result = {}
    engineer_error = {}
    marketing_error = {}

    def run_engineer():
        try:
            result = engineer_agent.run()
            if result:
                engineer_result.update(result)
        except Exception as e:
            engineer_error["error"] = str(e)
            print(f"\n[Engineer] ERROR: {e}")

    def run_marketing():
        try:
            result = marketing_agent.run()
            if result:
                marketing_result.update(result)
        except Exception as e:
            marketing_error["error"] = str(e)
            print(f"\n[Marketing] ERROR: {e}")

    t_engineer = threading.Thread(target=run_engineer)
    t_marketing = threading.Thread(target=run_marketing)

    t_engineer.start()
    t_marketing.start()
    t_engineer.join()
    t_marketing.join()

    print("\n[MAIN] Engineer and Marketing agents finished.")

    if engineer_error:
        print(f"[MAIN] Engineer failed: {engineer_error['error']}. Aborting.")
        return

    if marketing_error:
        print(f"[MAIN] Marketing failed: {marketing_error['error']}. Continuing without marketing.")

    # --- Step 5: QA review loop ---
    html = engineer_result.get("html", "")
    pr_url = engineer_result.get("pr_url", "")
    startup_name = engineer_result.get("startup_name", "Startup")
    folder_name = engineer_result.get("folder_name", startup_name.lower())
    copy = marketing_result.get("copy", {})

    qa_approved = False

    for qa_attempt in range(QA_MAX_RETRIES + 1):
        print(f"\n[MAIN] Sending to QA agent (attempt {qa_attempt + 1})...")

        # CEO sends task to QA
        ceo_agent.send_qa_task(
            spec=product_spec,
            html=html,
            pr_url=pr_url,
            folder_name=folder_name,
            marketing_copy=copy,
        )

        # QA agent runs
        qa_report = qa_agent.run()
        if not qa_report:
            print("[MAIN] QA agent returned nothing. Skipping QA.")
            qa_approved = True
            break

        # CEO reasons about QA report
        qa_decision = ceo_agent.handle_qa_report(qa_report, product_spec, task_message_id)

        if qa_decision["verdict"] == "accept":
            print("[MAIN] QA approved. Moving forward.")
            qa_approved = True
            break

        if qa_attempt < QA_MAX_RETRIES:
            # Re-run Engineer if HTML needs revision
            if qa_decision.get("engineer_feedback"):
                print("\n[MAIN] Re-running Engineer agent with CEO feedback...")
                new_engineer_result = engineer_agent.run()
                if new_engineer_result:
                    engineer_result.update(new_engineer_result)
                    html = new_engineer_result.get("html", html)
                    pr_url = new_engineer_result.get("pr_url", pr_url)

            # Re-run Marketing if copy needs revision
            if qa_decision.get("marketing_feedback"):
                print("\n[MAIN] Re-running Marketing agent with CEO feedback...")
                new_marketing_result = marketing_agent.run(
                    feedback=qa_decision["marketing_feedback"]
                )
                if new_marketing_result:
                    marketing_result.update(new_marketing_result)
                    copy = new_marketing_result.get("copy", copy)
        else:
            print("[MAIN] QA max retries reached. Proceeding with current output.")
            qa_approved = True

    # --- Step 6: CEO forwards PR link to Marketing, Marketing posts to Slack ---
    if qa_approved and pr_url:
        ceo_agent.forward_pr_to_marketing(pr_url, startup_name)

        if not marketing_result.get("slack_posted"):
            print("\n[MAIN] Marketing posting to Slack with approved PR link...")
            marketing_agent.post_slack_with_pr(
                pr_url=pr_url,
                startup_name=startup_name,
                copy=copy,
            )

    # --- Step 7: CEO posts final summary to Slack ---
    print("\n[MAIN] CEO posting final summary to Slack...")
    post_ceo_summary(idea, engineer_result, marketing_result)

    # --- Done ---
    print("\n" + "=" * 60)
    print("  PIPELINE COMPLETE")
    print("=" * 60)
    if engineer_result:
        print(f"\n  Startup: {engineer_result.get('startup_name')}")
        print(f"  Repo:    {engineer_result.get('repo')}")
        print(f"  PR:      {engineer_result.get('pr_url')}")
        print(f"  Issue:   {engineer_result.get('issue_url')}")

    print("\n[MAIN] Full message history:")
    history = get_history()
    for agent, messages in history.items():
        print(f"\n  [{agent.upper()}] sent {len(messages)} message(s):")
        for msg in messages:
            print(f"    → to: {msg['to_agent']} | type: {msg['message_type']} | id: {msg['message_id']}")


def post_ceo_summary(idea: str, engineer_result: dict, marketing_result: dict) -> None:
    """CEO posts final summary to Slack."""
    slack_token = os.environ["SLACK_BOT_TOKEN"]
    startup_name = engineer_result.get("startup_name", "Startup")
    pr_url = engineer_result.get("pr_url", "N/A")
    tagline = marketing_result.get("copy", {}).get("tagline", "N/A")

    payload = {
        "channel": "#launches",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"CEO Summary: {startup_name} is Live",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Original Idea:* {idea}\n*Tagline:* {tagline}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*PR:* <{pr_url}|View Pull Request>"},
                    {"type": "mrkdwn", "text": "*All agents:* Completed"},
                ],
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Posted by LaunchMind CEO Agent",
                    }
                ],
            },
        ],
    }

    r = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {slack_token}"},
        json=payload,
    )
    data = r.json()
    if data.get("ok"):
        print("[CEO] Final summary posted to Slack.")
    else:
        print(f"[CEO] Slack error: {data.get('error')}")

    send_message(
        from_agent="ceo",
        to_agent="ceo",
        message_type="result",
        payload={
            "status": "pipeline_complete",
            "startup_name": startup_name,
            "pr_url": pr_url,
            "tagline": tagline,
        },
    )


if __name__ == "__main__":
    idea = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "A subscription service that delivers weekly meal prep kits based on your gym goals"
    )
    run_pipeline(idea)