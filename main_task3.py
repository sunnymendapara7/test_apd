import os
import json
import logging
import re
import time
import base64
import requests
from github import Github
from groq import Groq
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    filename='jira_and_llm_tasks.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Load environment variables
load_dotenv()
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_USERNAME = os.getenv('GITHUB_USERNAME')
GITHUB_REPO = os.getenv('GITHUB_REPO')
JIRA_URL = os.getenv('JIRA_URL')  # e.g., https://your-domain.atlassian.net
JIRA_EMAIL = os.getenv('JIRA_EMAIL')
JIRA_API_TOKEN = os.getenv('JIRA_API_TOKEN')

def validate_env_vars():
    """Validate required environment variables."""
    required_vars = {
        'GROQ_API_KEY': GROQ_API_KEY,
        'GITHUB_TOKEN': GITHUB_TOKEN,
        'GITHUB_USERNAME': GITHUB_USERNAME,
        'GITHUB_REPO': GITHUB_REPO,
        'JIRA_URL': JIRA_URL,
        'JIRA_EMAIL': JIRA_EMAIL,
        'JIRA_API_TOKEN': JIRA_API_TOKEN
    }
    missing = [key for key, value in required_vars.items() if not value]
    if missing:
        error_msg = f"Missing environment variables: {', '.join(missing)}"
        logging.error(error_msg)
        print(f"Error: {error_msg}")
        return False
    if not JIRA_URL.startswith(('http://', 'https://')):
        error_msg = f"Invalid JIRA_URL: {JIRA_URL}. Must start with http:// or https://"
        logging.error(error_msg)
        print(f"Error: {error_msg}")
        return False
    return True

def read_ticket_keys(file_path):
    """Read and validate ticket_keys.json."""
    try:
        with open(file_path, 'r') as f:
            ticket_keys = json.load(f)
        for ticket in ticket_keys:
            if not all(key in ticket for key in ['key', 'summary', 'type']):
                raise ValueError(f"Invalid ticket entry: {ticket}. Missing required fields.")
        logging.info(f"Read {len(ticket_keys)} tickets from {file_path}")
        return ticket_keys
    except Exception as e:
        logging.error(f"Error reading ticket_keys.json: {e}")
        print(f"Error reading ticket_keys.json: {e}")
        return []

def call_groq_api(prompt, max_retries=3):
    """Call Groq API to generate test cases."""
    if not GROQ_API_KEY:
        logging.error("GROQ_API_KEY is not set")
        return None
    try:
        client = Groq(api_key=GROQ_API_KEY)
        for attempt in range(max_retries):
            try:
                response = client.chat.completions.create(
                    model="llama-3.1-70b-versatile",
                    messages=[
                        {"role": "system", "content": "You are a test case generator for a security service booking system."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=1000,
                    temperature=0.7
                )
                return response.choices[0].message.content
            except Exception as e:
                logging.warning(f"Groq API attempt {attempt + 1}/{max_retries} failed: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logging.error(f"Groq API call failed after {max_retries} attempts: {str(e)}")
                    return None
    except Exception as e:
        logging.error(f"Failed to initialize Groq client: {str(e)}")
        return None
    return None

def generate_fallback_test_case(task_key, task_info):
    """Generate a basic test case using acceptance criteria if Groq API fails."""
    test_case_content = f"# Test Cases for {task_key}: {task_info['summary']}\n\n"
    test_case_content += f"## Task Description\n{task_info['description']}\n\n"
    test_case_content += f"### Test Case TC_{task_key}_01\n"
    test_case_content += f"**Objective**: Verify {task_info['summary'].lower()} functionality.\n"
    test_case_content += "**Preconditions**: System is accessible, user is logged in (if applicable).\n"
    test_case_content += "**Test Steps**:\n"
    if task_info['acceptance_criteria']:
        for i, crit in enumerate(task_info['acceptance_criteria'], 1):
            test_case_content += f"{i}. Ensure {crit.lower()}.\n"
    else:
        test_case_content += "1. Verify the functionality as per the task description.\n"
    test_case_content += "**Expected Result**:\n"
    if task_info['acceptance_criteria']:
        for crit in task_info['acceptance_criteria']:
            test_case_content += f"- {crit}\n"
    else:
        test_case_content += f"- {task_info['description']}\n"
    test_case_content += "\n"

    if task_info['subtasks']:
        test_case_content += "## Subtask Test Cases\n"
        for subtask_key, subtask in task_info['subtasks'].items():
            test_case_content += f"### Test Case TC_{subtask_key}_01\n"
            test_case_content += f"**Objective**: Verify {subtask['summary'].lower()} functionality.\n"
            test_case_content += "**Preconditions**: Parent task functionality is available, user is logged in (if applicable).\n"
            test_case_content += "**Test Steps**:\n"
            if subtask['acceptance_criteria']:
                for i, crit in enumerate(subtask['acceptance_criteria'], 1):
                    test_case_content += f"{i}. Ensure {crit.lower()}.\n"
            else:
                test_case_content += "1. Verify the functionality as per the subtask description.\n"
            test_case_content += "**Expected Result**:\n"
            if subtask['acceptance_criteria']:
                for crit in subtask['acceptance_criteria']:
                    test_case_content += f"- {crit}\n"
            else:
                test_case_content += f"- {subtask['description']}\n"
            test_case_content += "\n"

    return test_case_content

def generate_test_cases(tasks):
    """Generate test cases using Groq API with fallback."""
    test_cases = {}
    for task_key, task_info in tasks.items():
        # Craft prompt for Groq
        prompt = (
            f"Generate test cases for the following task in a security service booking system:\n"
            f"Task ID: {task_key}\n"
            f"Summary: {task_info['summary']}\n"
            f"Description: {task_info['description']}\n"
            f"Acceptance Criteria:\n" +
            (("\n".join([f"- {crit}" for crit in task_info['acceptance_criteria']]) + "\n") if task_info['acceptance_criteria'] else "- None\n") +
            f"\nFormat each test case in Markdown with sections: Objective, Preconditions, Test Steps (numbered), Expected Result. "
            f"Generate one test case for the task and one for each subtask (if any) under a 'Subtask Test Cases' section.\n"
            f"Subtasks:\n"
        )
        for subtask_key, subtask in task_info['subtasks'].items():
            prompt += (
                f"Subtask ID: {subtask_key}\n"
                f"Summary: {subtask['summary']}\n"
                f"Description: {subtask['description']}\n"
                f"Acceptance Criteria:\n" +
                (("\n".join([f"- {crit}" for crit in subtask['acceptance_criteria']]) + "\n") if subtask['acceptance_criteria'] else "- None\n") +
                "\n"
            )
        prompt += "Ensure test cases are specific, actionable, and cover all acceptance criteria."

        # Call Groq API
        test_case_content = call_groq_api(prompt)
        if not test_case_content:
            logging.warning(f"Using fallback test case generation for {task_key}")
            test_case_content = generate_fallback_test_case(task_key, task_info)
        else:
            # Ensure content starts with proper header
            if not test_case_content.startswith(f"# Test Cases for {task_key}"):
                test_case_content = (
                    f"# Test Cases for {task_key}: {task_info['summary']}\n\n"
                    f"## Task Description\n{task_info['description']}\n\n" +
                    test_case_content
                )

        test_cases[task_key] = test_case_content
        logging.info(f"Generated test cases for {task_key}")
    return test_cases

def add_test_cases_to_jira(task_key, test_content):
    """Add test cases as a comment to the Jira ticket."""
    # Skip if test_content is empty or contains only fallback error message
    if "Failed to generate test cases" in test_content:
        logging.warning(f"Skipping Jira comment for {task_key} due to empty test cases")
        return

    try:
        headers = {
            'Authorization': f'Basic {base64.b64encode(f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()).decode()}',
            'Content-Type': 'application/json'
        }
        # Ensure JIRA_URL ends with a slash
        jira_base_url = JIRA_URL.rstrip('/') + '/'
        url = f"{jira_base_url}rest/api/3/issue/{task_key}/comment"
        payload = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "Generated Test Cases:\n\n" + test_content
                            }
                        ]
                    }
                ]
            }
        }
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        logging.info(f"Added test cases as comment to Jira ticket {task_key}")
        print(f"Added test cases to Jira ticket {task_key}")
    except Exception as e:
        logging.error(f"Failed to add test cases to Jira ticket {task_key}: {str(e)}")
        print(f"Error adding test cases to Jira ticket {task_key}: {str(e)}")

def commit_test_cases(repo, test_cases, tasks):
    """Commit test case Markdown files to GitHub feature branches."""
    for task_key, test_content in test_cases.items():
        try:
            sanitized_summary = re.sub(r'[^a-zA-Z0-9\s-]', '', tasks[task_key]['summary']).lower().replace(' ', '-')
            branch_name = f"feature/{task_key}-{sanitized_summary}"[:50]
            file_name = f"test_cases_{task_key}.md"

            # Verify branch exists
            try:
                repo.get_branch(branch_name)
            except:
                logging.warning(f"Branch {branch_name} does not exist")
                print(f"Error: Branch {branch_name} does not exist. Skipping.")
                continue

            # Commit test case file
            try:
                contents = repo.get_contents(file_name, ref=branch_name)
                repo.update_file(
                    file_name,
                    f"Update {file_name} for {task_key}",
                    test_content,
                    contents.sha,
                    branch=branch_name
                )
                logging.info(f"Updated {file_name} in branch {branch_name}")
                print(f"Updated {file_name} in branch {branch_name}")
            except:
                repo.create_file(
                    file_name,
                    f"Add {file_name} for {task_key}",
                    test_content,
                    branch=branch_name
                )
                logging.info(f"Created {file_name} in branch {branch_name}")
                print(f"Created {file_name} in branch {branch_name}")

        except Exception as e:
            logging.error(f"Error committing test cases for {task_key} to {branch_name}: {str(e)}")
            print(f"Error committing test cases for {task_key}: {str(e)}")

def save_test_cases_to_text_file(test_cases, output_file='all_test_cases.txt'):
    """Save all test cases to a single text file."""
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("# All Test Cases for Body Guard Booking System\n\n")
            for task_key, test_content in test_cases.items():
                f.write(test_content)
                f.write("\n---\n")  # Separator between tasks
        logging.info(f"Saved all test cases to {output_file}")
        print(f"Saved all test cases to {output_file}")
    except Exception as e:
        logging.error(f"Error saving test cases to {output_file}: {str(e)}")
        print(f"Error saving test cases to {output_file}: {str(e)}")

def main():
    """Main function to generate test cases, add to Jira, commit to GitHub, and save to text file."""
    if not validate_env_vars():
        return

    ticket_keys = read_ticket_keys('ticket_keys.json')
    if not ticket_keys:
        logging.error("No ticket keys found.")
        print("Error: No ticket keys found.")
        return

    # Organize tasks and subtasks
    tasks = {}
    for ticket in ticket_keys:
        ticket_key = ticket['key']
        if ticket['type'] == 'Task':
            tasks[ticket_key] = {
                'summary': ticket['summary'],
                'description': ticket.get('description', 'No description available.'),
                'acceptance_criteria': ticket.get('acceptance_criteria', []),
                'subtasks': {}
            }
        elif ticket['type'] == 'Subtask':
            parent_key = ticket.get('parent_key')
            if parent_key and parent_key in tasks:
                tasks[parent_key]['subtasks'][ticket_key] = {
                    'summary': ticket['summary'],
                    'description': ticket.get('description', 'No description available.'),
                    'acceptance_criteria': ticket.get('acceptance_criteria', [])
                }

    # Generate test cases using Groq API
    test_cases = generate_test_cases(tasks)

    # Save test cases to text file
    save_test_cases_to_text_file(test_cases)

    # Connect to GitHub
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_user().get_repo(GITHUB_REPO)
        logging.info(f"Connected to repository: {repo.html_url}")

        # Add test cases to Jira and commit to GitHub
        for task_key in test_cases:
            add_test_cases_to_jira(task_key, test_cases[task_key])
            commit_test_cases(repo, {task_key: test_cases[task_key]}, tasks)

        logging.info(f"Test case generation, Jira update, GitHub commit, and text file creation completed.")
        print(f"Test case generation, Jira update, GitHub commit, and text file creation completed successfully.")
    except Exception as e:
        logging.error(f"Error accessing GitHub repository: {str(e)}")
        print(f"Error: Failed to access repository: {str(e)}")

if __name__ == '__main__':
    main()