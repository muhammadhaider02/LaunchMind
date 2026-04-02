import json
import sys
import os

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "agents"))

from message_bus import get_history
import ceo_agent
import product_agent
import engineer_agent

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

    # --- Step 3: CEO reviews product spec ---
    review_result = ceo_agent.review_and_proceed(product_spec, task_message_id)

    # --- Step 4: Handle revision if needed ---
    if review_result.get("needs_revision"):
        print(f"\n[MAIN] CEO requested revision. Re-running Product agent...")
        product_spec = product_agent.run(feedback=review_result["feedback"])
        if not product_spec:
            print("\n[MAIN] Product agent returned nothing on revision. Aborting.")
            return
        review_result = ceo_agent.review_and_proceed(product_spec, task_message_id)

    final_spec = review_result
    print("\n[MAIN] Product spec accepted. Handing off to Engineer agent...")

    # --- Step 5: Engineer agent runs (parallel with Marketing — Marketing coming soon) ---
    engineer_result = engineer_agent.run()
    if not engineer_result:
        print("\n[MAIN] Engineer agent returned nothing. Aborting.")
        return

    # --- Done ---
    print("\n" + "=" * 60)
    print("  PIPELINE COMPLETE")
    print("=" * 60)
    print(f"\n  Repo:  {engineer_result['repo']}")
    print(f"  PR:    {engineer_result['pr_url']}")
    print(f"  Issue: {engineer_result['issue_url']}")

    print("\n[MAIN] Full message history:")
    history = get_history()
    for agent, messages in history.items():
        print(f"\n  [{agent.upper()}] sent {len(messages)} message(s):")
        for msg in messages:
            print(f"    → to: {msg['to_agent']} | type: {msg['message_type']} | id: {msg['message_id']}")


if __name__ == "__main__":
    idea = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "A platform where university students can list and buy second-hand textbooks"
    )
    run_pipeline(idea)