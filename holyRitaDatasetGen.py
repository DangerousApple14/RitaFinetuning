import json
import time
import random
import itertools
from pathlib import Path
from openai import OpenAI
from instructs import *


# ============================================================
# HOLY RITA DATASET GENERATOR
# ============================================================
#
# Run:
#
#     python holyRitaDatasetGen.py
#
# Uses:
#     Ollama + Qwen 2.5 14B
#
# Generates:
#     dataset_rita_instruct.jsonl
#
# ============================================================


# ============================================================
# CONFIG
# ============================================================

MODEL_NAME = "qwen2.5:14b"

OUTPUT_FILE = "dataset_rita_instruct.jsonl"

# Total desired number of rows.
TARGET_ROWS = 5000

# True  = output contains a short analysis + Rita response
# False = output contains ONLY Rita's actual response
KEEP_COT = True

# Qwen creativity.
TEMPERATURE = 0.9

# Small delay after failed requests.
RETRY_DELAY = 0.5

# Maximum number of generation failures before aborting.
MAX_CONSECUTIVE_FAILURES = 20


# ============================================================
# OLLAMA CLIENT
# ============================================================

client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama"
)


# ============================================================
# BUILD SHUFFLED COMBINATION POOL
# ============================================================

def build_scenario_pool():
    """
    Creates a shuffled Cartesian product of all behavioral dimensions.

    This is intentionally NOT random.choice().

    random.choice() can accidentally reuse the same kinds of examples
    many times while never touching others.

    This pool guarantees that every combination appears at most once
    during a pass through the pool.
    """

    pool = list(
        itertools.product(
            SCENARIO_SEEDS,
            USER_ARCHETYPES,
            USER_MOODS,
            ESCALATION_LEVELS,
            MESSAGE_STYLES,
        )
    )

    random.shuffle(pool)

    return pool


# ============================================================
# LOAD EXISTING DATASET
# ============================================================

def load_existing_dataset(path):
    """
    Loads existing JSONL rows so the script can resume safely.

    Returns:
        rows
        existing_inputs
    """

    rows = []
    existing_inputs = set()

    if not path.exists():
        return rows, existing_inputs

    print(f"Existing dataset found: {path}")
    print("Loading previous rows...")

    with open(path, "r", encoding="utf-8") as f:

        for line_number, line in enumerate(f, start=1):

            line = line.strip()

            if not line:
                continue

            try:
                data = json.loads(line)

                if not isinstance(data, dict):
                    continue

                if not all(
                    key in data
                    for key in ("instructions", "input", "output")
                ):
                    continue

                user_input = str(data["input"]).strip()

                if not user_input:
                    continue

                rows.append(data)
                existing_inputs.add(user_input)

            except json.JSONDecodeError:

                print(
                    f"\nWarning: invalid JSON on line {line_number}. "
                    f"Skipping it."
                )

    print(f"Loaded {len(rows):,} valid existing rows.")

    return rows, existing_inputs


# ============================================================
# BUILD GENERATION PROMPT
# ============================================================

def build_prompt(
    scenario,
    archetype,
    mood,
    escalation,
    message_style,
):

    # Choose whether this dataset contains analysis.
    if KEEP_COT:
        output_instruction = COT_OUTPUT_RULES
    else:
        output_instruction = CLEAN_OUTPUT_RULES

    # Convert the emote list into text for the prompt.
    emote_text = "\n".join(
        f"- {emote}"
        for emote in RITA_EMOTES
    )

    return f"""
Act as a specialized synthetic-data generator for a fine-tuning
dataset.

Generate ONE unique Discord user message and ONE Rita response.

{RITA_BEHAVIOR}

{RITA_EMOTE_RULES}

### Available Emotes

{emote_text}

{RITA_EMOTE_GUIDE}

### Current Generation Parameters

Scenario:
{scenario}

User archetype:
{archetype}

User mood:
{mood}

Escalation level:
{escalation}

Message style:
{message_style}

{USER_MESSAGE_RULES}

{RITA_RESPONSE_RULES}

{output_instruction}

{OUTPUT_RULES}

The "instructions" value MUST be exactly:

{json.dumps(INSTRUCTIONS)}
"""

def generate_rita_line(
    scenario,
    archetype,
    mood,
    escalation,
    message_style,
):

    prompt = build_prompt(
        scenario=scenario,
        archetype=archetype,
        mood=mood,
        escalation=escalation,
        message_style=message_style,
    )

    try:

        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            temperature=TEMPERATURE,
            response_format={"type": "json_object"},
        )

        raw_content = response.choices[0].message.content

        if not raw_content:
            raise ValueError("Model returned empty content.")

        raw_content = raw_content.strip()

        data = json.loads(raw_content)

        if not isinstance(data, dict):
            raise ValueError(
                "Model returned something other than a JSON object."
            )

        required_keys = {
            "instructions",
            "input",
            "output",
        }

        missing_keys = required_keys - set(data.keys())

        if missing_keys:
            raise ValueError(
                f"Missing keys: {missing_keys}"
            )

        user_input = str(data["input"]).strip()
        output = str(data["output"]).strip()

        if not user_input:
            raise ValueError("Empty input.")

        if not output:
            raise ValueError("Empty output.")

        return {
            "instructions": INSTRUCTIONS,
            "input": user_input,
            "output": output,
        }

    except Exception as e:

        print(
            f"\n[Generation error] {type(e).__name__}: {e}"
        )

        return None


# ============================================================
# MAIN
# ============================================================

def main():

    output_path = Path(OUTPUT_FILE)

    print()
    print("=" * 70)
    print("              HOLY RITA DATASET GENERATOR")
    print("=" * 70)
    print()
    print(f"Model:            {MODEL_NAME}")
    print(f"Target rows:      {TARGET_ROWS:,}")
    print(f"CoT enabled:      {KEEP_COT}")
    print(f"Temperature:      {TEMPERATURE}")
    print(f"Output file:      {OUTPUT_FILE}")
    print()

    # --------------------------------------------------------
    # Load existing dataset
    # --------------------------------------------------------

    existing_rows, existing_inputs = load_existing_dataset(
        output_path
    )

    existing_count = len(existing_rows)

    if existing_count >= TARGET_ROWS:

        print()
        print(
            f"Dataset already contains {existing_count:,} rows."
        )
        print(
            f"Target is {TARGET_ROWS:,}. Nothing to generate."
        )
        print()
        return

    remaining = TARGET_ROWS - existing_count

    print()
    print(
        f"Need to generate {remaining:,} more rows."
    )

    # --------------------------------------------------------
    # Build shuffled scenario pool
    # --------------------------------------------------------

    print()
    print("Building scenario combination pool...")

    scenario_pool = build_scenario_pool()

    print(
        f"Available unique combinations this pass: "
        f"{len(scenario_pool):,}"
    )

    print()

    # --------------------------------------------------------
    # Generation
    # --------------------------------------------------------

    generated_this_run = 0
    consecutive_failures = 0

    try:

        with open(
            output_path,
            "a",
            encoding="utf-8",
        ) as f:

            while existing_count + generated_this_run < TARGET_ROWS:

                # Rebuild and reshuffle after an entire pass.
                if not scenario_pool:

                    print(
                        "\n\nScenario pool exhausted."
                    )

                    print(
                        "Building a new shuffled pass..."
                    )

                    scenario_pool = build_scenario_pool()

                (
                    scenario,
                    archetype,
                    mood,
                    escalation,
                    message_style,
                ) = scenario_pool.pop()

                result = generate_rita_line(
                    scenario=scenario,
                    archetype=archetype,
                    mood=mood,
                    escalation=escalation,
                    message_style=message_style,
                )

                # ------------------------------------------------
                # Failed generation
                # ------------------------------------------------

                if result is None:

                    consecutive_failures += 1

                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:

                        print()
                        print()
                        print(
                            "Too many consecutive generation failures."
                        )
                        print(
                            "Stopping so you can inspect Ollama."
                        )

                        break

                    time.sleep(RETRY_DELAY)

                    continue

                # ------------------------------------------------
                # Duplicate input protection
                # ------------------------------------------------

                user_input = result["input"]

                if user_input in existing_inputs:

                    print(
                        "\n[Duplicate input detected — skipping]"
                    )

                    continue

                # ------------------------------------------------
                # Successful generation
                # ------------------------------------------------

                consecutive_failures = 0

                jsonl_line = json.dumps(
                    result,
                    ensure_ascii=False,
                )

                f.write(jsonl_line + "\n")

                # Extremely important:
                # flush after EVERY successful example.
                #
                # This means Ctrl+C loses essentially nothing.
                f.flush()

                existing_inputs.add(user_input)

                generated_this_run += 1

                total_now = (
                    existing_count
                    + generated_this_run
                )

                # ------------------------------------------------
                # Progress display
                # ------------------------------------------------

                print(
                    (
                        f"Generated "
                        f"{total_now:,}/{TARGET_ROWS:,} | "
                        f"{archetype} | "
                        f"{mood} | "
                        f"{escalation}"
                    ).ljust(130),
                    end="\r",
                )

    except KeyboardInterrupt:

        print()
        print()
        print("Stopped with CTRL+C.")
        print(
            f"Rows already saved: "
            f"{existing_count + generated_this_run:,}"
        )

    # --------------------------------------------------------
    # Final message
    # --------------------------------------------------------

    final_count = existing_count + generated_this_run

    print()
    print()
    print("=" * 70)
    print("GENERATION FINISHED")
    print("=" * 70)
    print()
    print(f"Dataset file:     {OUTPUT_FILE}")
    print(f"Rows in dataset:  {final_count:,}")
    print(f"Target rows:      {TARGET_ROWS:,}")
    print(f"CoT enabled:      {KEEP_COT}")
    print()

    if final_count >= TARGET_ROWS:

        print("Holy Rita is ready for Unsloth.")
        print()

    else:

        print(
            "Generation stopped before reaching the target."
        )

        print(
            "Run the script again to continue."
        )

        print()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()