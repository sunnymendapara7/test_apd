import os
import re
import requests
import json
from dotenv import load_dotenv
from docx import Document
import PyPDF2
from jira import JIRA
from jira.exceptions import JIRAError
import logging
from datetime import datetime

# Setup logging for operations
logging.basicConfig(
    filename='jira_and_llm_tasks.log',
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Load environment variables from .env file
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
JIRA_SERVER = os.getenv('JIRA_SERVER')
JIRA_EMAIL = os.getenv('JIRA_EMAIL')
JIRA_API_TOKEN = os.getenv('JIRA_API_TOKEN')
JIRA_PROJECT_KEY = os.getenv('JIRA_PROJECT_KEY')
MODEL = "llama3-70b-8192"  # Change as needed
DEFAULT_ISSUE_TYPE = os.getenv('DEFAULT_ISSUE_TYPE', 'Task')
DEFAULT_SUBTASK_ISSUE_TYPE = os.getenv('DEFAULT_SUBTASK_ISSUE_TYPE', 'Subtask')

# Validate Jira connection and issue types
def validate_jira_connection():
    global DEFAULT_ISSUE_TYPE, DEFAULT_SUBTASK_ISSUE_TYPE
    print(f"Attempting to connect to Jira server: {JIRA_SERVER}")
    print(f"Using email: {JIRA_EMAIL}, project key: {JIRA_PROJECT_KEY}")
    if not all([JIRA_SERVER, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY]):
        missing_vars = [var for var, val in [
            ('JIRA_SERVER', JIRA_SERVER),
            ('JIRA_EMAIL', JIRA_EMAIL),
            ('JIRA_API_TOKEN', JIRA_API_TOKEN),
            ('JIRA_PROJECT_KEY', JIRA_PROJECT_KEY)
        ] if not val]
        error_msg = f"Missing environment variables: {', '.join(missing_vars)}"
        logging.error(error_msg)
        print(f"Error: {error_msg}")
        return None

    try:
        jira = JIRA(server=JIRA_SERVER, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))
        print("Jira connection established successfully")
        project = jira.project(JIRA_PROJECT_KEY)
        logging.info(f"Validated project: {JIRA_PROJECT_KEY}")
        print(f"Validated project: {JIRA_PROJECT_KEY}")
        issue_types = jira.issue_types_for_project(project.id)
        issue_type_names = [it.name for it in issue_types]
        logging.info(f"Available issue types for project {JIRA_PROJECT_KEY}: {issue_type_names}")
        print(f"Available issue types: {issue_type_names}")
        if DEFAULT_ISSUE_TYPE not in issue_type_names:
            logging.warning(f"Issue type '{DEFAULT_ISSUE_TYPE}' not available, trying 'Task', 'Story', or 'Issue'")
            print(f"Warning: Issue type '{DEFAULT_ISSUE_TYPE}' not available, trying 'Task', 'Story', or 'Issue'")
            fallback_types = ['Task', 'Story', 'Issue']
            valid_type = next((t for t in fallback_types if t in issue_type_names), None)
            if not valid_type:
                logging.error("No valid issue type found")
                print("Error: No valid task issue type found")
                return None
            DEFAULT_ISSUE_TYPE = valid_type
            logging.info(f"Falling back to task issue type: {DEFAULT_ISSUE_TYPE}")
            print(f"Falling back to task issue type: {DEFAULT_ISSUE_TYPE}")
        if DEFAULT_SUBTASK_ISSUE_TYPE not in issue_type_names:
            logging.warning(f"Subtask issue type '{DEFAULT_SUBTASK_ISSUE_TYPE}' not available, trying 'Sub-task' or 'Subtask'")
            print(f"Warning: Subtask issue type '{DEFAULT_SUBTASK_ISSUE_TYPE}' not available, trying 'Sub-task' or 'Subtask'")
            fallback_subtask_types = ['Sub-task', 'Subtask']
            valid_subtask_type = next((t for t in fallback_subtask_types if t in issue_type_names), None)
            if not valid_subtask_type:
                logging.warning("No valid subtask issue type found")
                print("Warning: Subtasks may be disabled. Tasks will be created without subtasks.")
            else:
                DEFAULT_SUBTASK_ISSUE_TYPE = valid_subtask_type
                logging.info(f"Falling back to subtask issue type: {DEFAULT_SUBTASK_ISSUE_TYPE}")
                print(f"Falling back to subtask issue type: {DEFAULT_SUBTASK_ISSUE_TYPE}")
        return jira
    except JIRAError as e:
        logging.error(f"Jira API error: {e.status_code} - {e.text}")
        print(f"Error: Jira API error for project {JIRA_PROJECT_KEY}: {e.status_code} - {e.text}")
        return None
    except Exception as e:
        logging.error(f"Failed to connect to Jira: {e}")
        print(f"Error: Cannot connect to Jira: {e}")
        return None

# Step 1: Extract text from document and save as .txt
def extract_text_to_txt(input_path, output_txt_path):
    try:
        text = ""
        if input_path.endswith(".txt"):
            with open(input_path, "r", encoding="utf-8") as f:
                text = f.read()
        elif input_path.endswith(".pdf"):
            with open(input_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                text = "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
        elif input_path.endswith(".docx"):
            doc = Document(input_path)
            text = "\n".join(p.text for p in doc.paragraphs)
        else:
            raise ValueError("Unsupported file type. Use .txt, .pdf, or .docx")

        with open(output_txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Extracted text saved to {output_txt_path}")
        logging.info(f"Extracted text from {input_path} to {output_txt_path}")
        return output_txt_path
    except Exception as e:
        logging.error(f"Failed to extract text from {input_path}: {e}")
        print(f"Error: Failed to extract text: {e}")
        raise

# Step 2: Load text from .txt file
def read_txt_file(txt_file_path):
    try:
        with open(txt_file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logging.error(f"Failed to read text from {txt_file_path}: {e}")
        print(f"Error: Failed to read text: {e}")
        raise

# Step 3: Prompt for Groq API to extract tasks and subtasks
def generate_prompt(doc_text):
    return f"""
You are a project planner AI specialized in converting requirement documents into detailed, developer-ready tasks and subtasks.

Instructions:
- Extract tasks and subtasks from the requirement document.
- Identify top-level sections (e.g., "Dashboard", "Venues Management", "Users Management", "Reporting & Analytics", "Roles & Permissions", "Additional Features & Enhancements", "KPIs to Track for Growth") as individual tasks.
- Do NOT treat subsections (e.g., "Referrals" under "Dashboard", "Venue Performance Metrics" under "Venues Management") as separate tasks; instead, include them as subtasks under their respective parent tasks.
- Ignore sections that are not actionable development tasks (e.g., "Overview", "Implementation Timeline").
- Treat the "KPIs to Track for Growth" section as an actionable task by interpreting it as "Implement tracking for the listed KPIs" and break down each KPI into a subtask.
- For each task and subtask, provide:
  1. A concise, descriptive title.
  2. A detailed explanation of what should be done.
  3. Acceptance criteria or key points the developer must satisfy (only include criteria that define success, not actionable subtasks).
- Use clear and precise language suitable for developers.
- Number tasks and subtasks sequentially (e.g., Task 1, Task 2, Subtask 1.1, Subtask 1.2, etc.).
- Ensure subtasks are correctly associated with their parent tasks (e.g., Subtask 9.1 must be under Task 9, not Task 8).
- Do NOT include any text like "(Phase 1)" or "(Phase 2)" in titles, descriptions, or acceptance criteria; treat all requirements as part of the current scope.
- Do NOT use any special symbols (e.g., asterisks, emojis, or other markdown symbols like "**") for task or subtask titles.
- Output format:
  - Use the exact string "Task X: <Task Title>" for tasks.
  - Use the exact string "Subtask X.Y: <Subtask Title>" for subtasks.

Example output format:

Task 1: Dashboard Development
Description: Develop a dashboard to display critical metrics.
Acceptance Criteria:
- Dashboard is accessible to admins
- Metrics are displayed accurately

Subtask 1.1: User Metrics Implementation
Description: Implement user metrics on the dashboard.
Acceptance Criteria:
- Total registered users are displayed
- Active vs. inactive users are displayed

Subtask 1.2: Referrals Metrics Implementation
Description: Implement referrals metrics on the dashboard.
Acceptance Criteria:
- Number of referrals sent is displayed

Task 2: Venues Management
Description: Develop a module to manage venues.
Acceptance Criteria:
- Venue profiles can be managed

Subtask 2.1: Venue Performance Metrics Implementation
Description: Implement venue performance metrics.
Acceptance Criteria:
- Total bookings are tracked

Now, analyze the following requirement document and extract tasks accordingly:

\"\"\"
{doc_text}
\"\"\"
"""

# Step 4: Query Groq API to extract tasks and subtasks and save to text file
def extract_task_structure_with_groq(doc_text, output_task_file):
    if not GROQ_API_KEY:
        logging.error("GROQ_API_KEY is not set.")
        print("Error: GROQ_API_KEY is not set.")
        return ""

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": generate_prompt(doc_text)}
        ],
        "model": MODEL
    }

    try:
        response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
        if response.status_code == 200:
            content = response.json().get("choices", [])[0]["message"]["content"]
            # Clean any leftover (Phase X) just in case
            cleaned_content = re.sub(r"\s*\(Phase\s*\d+\)", "", content).strip()
            # Save to text file
            with open(output_task_file, "w", encoding="utf-8") as f:
                f.write(cleaned_content)
            print(f"Extracted tasks saved to {output_task_file}")
            logging.info(f"Extracted tasks saved to {output_task_file}")
            return cleaned_content
        else:
            raise Exception(f"Error from Groq API: {response.status_code} - {response.text}")
    except Exception as e:
        logging.error(f"Failed to extract tasks from Groq API: {e}")
        print(f"Error: Failed to extract tasks from Groq API: {e}")
        return ""

# Step 5: Parse tasks and subtasks from text file
def parse_tasks_from_file(task_file_path):
    try:
        with open(task_file_path, "r", encoding="utf-8") as f:
            extracted_text = f.read()

        tasks = []
        current_task = None
        current_subtask = None
        lines = extracted_text.split('\n')

        task_pattern = re.compile(r'Task (\d+): (.+)')
        subtask_pattern = re.compile(r'Subtask (\d+\.\d+): (.+)')
        description_pattern = re.compile(r'Description: (.+)')
        acceptance_criteria_start = re.compile(r'Acceptance Criteria:')

        task_counter = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for a new task
            task_match = task_pattern.match(line)
            if task_match:
                task_number = int(task_match.group(1))
                task_counter = task_number
                if current_task:
                    tasks.append(current_task)
                current_task = {
                    'title': task_match.group(2),
                    'description': '',
                    'acceptance_criteria': [],
                    'subtasks': []
                }
                logging.info(f"Parsed Task {task_number}: {current_task['title']}")
                continue

            # Check for a new subtask
            subtask_match = subtask_pattern.match(line)
            if subtask_match and current_task:
                subtask_number = subtask_match.group(1)
                expected_prefix = f"{task_counter}."
                if not subtask_number.startswith(expected_prefix):
                    logging.warning(f"Subtask {subtask_number} does not match parent task {task_counter}. Adjusting...")
                    subtask_number = f"{task_counter}.{subtask_number.split('.')[-1]}"
                if current_subtask:
                    current_task['subtasks'].append(current_subtask)
                current_subtask = {
                    'title': subtask_match.group(2),
                    'description': '',
                    'acceptance_criteria': []
                }
                logging.info(f"Parsed Subtask {subtask_number}: {current_subtask['title']} under Task {task_counter}")
                continue

            # Check for description
            description_match = description_pattern.match(line)
            if description_match:
                if current_subtask:
                    current_subtask['description'] = description_match.group(1)
                    logging.info(f"Subtask Description: {current_subtask['description']}")
                elif current_task:
                    current_task['description'] = description_match.group(1)
                    logging.info(f"Task Description: {current_task['description']}")
                continue

            # Check for acceptance criteria
            if acceptance_criteria_start.match(line):
                continue
            if line.startswith('- ') and (current_task or current_subtask):
                criterion = line[2:].strip()
                if current_subtask:
                    current_subtask['acceptance_criteria'].append(criterion)
                    logging.info(f"Subtask Acceptance Criterion: {criterion}")
                elif current_task:
                    current_task['acceptance_criteria'].append(criterion)
                    logging.info(f"Task Acceptance Criterion: {criterion}")

        # Append the last task and subtask
        if current_subtask and current_task:
            current_task['subtasks'].append(current_subtask)
        if current_task:
            tasks.append(current_task)

        print(f"Parsed {len(tasks)} tasks from {task_file_path}")
        logging.info(f"Parsed tasks: {json.dumps(tasks, indent=2)}")
        return tasks
    except Exception as e:
        logging.error(f"Failed to parse tasks from {task_file_path}: {e}")
        print(f"Error: Failed to parse tasks: {e}")
        raise

# Step 6: Create Jira tickets
def create_jira_tickets(jira, tasks):
    ticket_keys = []
    output_display = []
    task_key_mapping = {}  # Map task titles to Jira ticket keys

    print(f"Total tasks to process: {len(tasks)}")
    for task_index, task in enumerate(tasks, 1):
        try:
            # Create the parent task ticket
            task_description = f"Description: {task['description']}\n\nAcceptance Criteria:\n" + "\n".join([f"- {crit}" for crit in task['acceptance_criteria']])
            issue_dict = {
                'project': {'key': JIRA_PROJECT_KEY},
                'summary': task['title'][:255],
                'description': task_description,
                'issuetype': {'name': DEFAULT_ISSUE_TYPE},
                'labels': ['Admin-Portal-Enhancements']
            }
            print(f"Creating Jira task ticket: {task['title']} with issue type: {DEFAULT_ISSUE_TYPE}")
            task_ticket = jira.create_issue(fields=issue_dict)
            task_key = task_ticket.key
            task_key_mapping[task['title']] = task_key
            logging.info(f"Created Jira task ticket: {task_key} - {task['title']}")
            ticket_keys.append({
                'key': task_key,
                'summary': task['title'],
                'type': DEFAULT_ISSUE_TYPE,
                'description': task['description'],
                'acceptance_criteria': task['acceptance_criteria']
            })
            output_display.append(f"Task: {task['title']} ({task_key})")

            # Create subtasks
            created_subtasks = []
            print(f"Total subtasks for {task['title']}: {len(task['subtasks'])}")
            for subtask in task['subtasks']:
                subtask_title = re.sub(r'Subtask \d+\.\d+:', '', subtask['title']).strip()
                subtask_description = f"Description: {subtask['description']}\n\nAcceptance Criteria:\n" + "\n".join([f"- {crit}" for crit in subtask['acceptance_criteria']])
                subtask_issue_dict = {
                    'project': {'key': JIRA_PROJECT_KEY},
                    'summary': subtask_title[:255],
                    'description': subtask_description,
                    'issuetype': {'name': DEFAULT_SUBTASK_ISSUE_TYPE},
                    'parent': {'key': task_key},
                    'labels': ['Admin-Portal-Enhancements']
                }
                print(f"Creating Jira subtask ticket: {subtask_title} under {task_key} with issue type: {DEFAULT_SUBTASK_ISSUE_TYPE}")
                subtask_ticket = jira.create_issue(fields=subtask_issue_dict)
                subtask_key = subtask_ticket.key
                logging.info(f"Created Jira subtask ticket: {subtask_key} - {subtask_title}")
                ticket_keys.append({
                    'key': subtask_key,
                    'summary': subtask_title,
                    'type': DEFAULT_SUBTASK_ISSUE_TYPE,
                    'parent_key': task_key,
                    'description': subtask['description'],
                    'acceptance_criteria': subtask['acceptance_criteria']
                })
                created_subtasks.append(f"Subtask: {subtask_title} ({subtask_key})")

            if not created_subtasks:
                output_display.append("Warning: No subtasks created for this task")
            else:
                output_display.extend(created_subtasks)
            output_display.append("")

        except JIRAError as e:
            logging.error(f"Jira API error creating ticket for {task['title']}: {e.status_code} - {e.text}")
            print(f"Failed to create ticket for '{task['title']}': {e.status_code} - {e.text}")
            continue
        except Exception as e:
            logging.error(f"Error creating Jira ticket for {task['title']}: {e}")
            print(f"Failed to create ticket for '{task['title']}': {e}")
            continue

    try:
        with open('ticket_keys.json', 'w') as f:
            json.dump(ticket_keys, f, indent=2)
        print("Ticket keys saved to ticket_keys.json")
        logging.info(f"Saved {len(ticket_keys)} ticket keys to ticket_keys.json")
    except Exception as e:
        logging.error(f"Error: Failed to save ticket keys to ticket_keys.json: {e}")
        print(f"Error: Failed to save ticket keys: {e}")

    if output_display:
        print("\nCreated Jira Tickets:\n")
        print("\n".join(output_display))
    else:
        print("No tasks or subtasks were successfully created.")

    return ticket_keys

def main():
    input_file_path = "Body guard booking services (2).docx"  # Updated file name to avoid spaces
    temp_txt_path = "temp_extracted_text.txt"
    task_file_path = "extracted_tasks.txt"

    # Validate input file
    if not os.path.exists(input_file_path):
        logging.error(f"Input file {input_file_path} does not exist.")
        print(f"Error: Input file {input_file_path} does not exist.")
        return
    if not input_file_path.lower().endswith(('.txt', '.pdf', '.docx')):
        logging.error("Unsupported file type. Use .txt, .pdf, or .docx")
        print("Error: Unsupported file type. Use .txt, .pdf, or .docx")
        return

    # Step 1: Extract text and save as .txt
    try:
        extract_text_to_txt(input_file_path, temp_txt_path)
    except Exception as e:
        logging.error(f"Failed to extract text from {input_file_path}: {e}")
        print(f"Error: Failed to extract text: {e}")
        return

    # Step 2: Read from extracted text file
    try:
        document_text = read_txt_file(temp_txt_path)
    except Exception as e:
        logging.error(f"Failed to read text from {temp_txt_path}: {e}")
        print(f"Error: Failed to read text: {e}")
        return

    # Step 3: Send text to Groq API and save tasks to text file
    extracted_tasks_text = extract_task_structure_with_groq(document_text, task_file_path)
    if not extracted_tasks_text:
        logging.error("No tasks extracted from Groq API.")
        print("Error: No tasks extracted. Aborting.")
        return

    print("\nExtracted Tasks:\n")
    print(extracted_tasks_text)

    # Step 4: Parse tasks from text file
    try:
        tasks = parse_tasks_from_file(task_file_path)
    except Exception as e:
        logging.error(f"Failed to parse tasks from {task_file_path}: {e}")
        print(f"Error: Failed to parse tasks: {e}")
        return

    # Step 5: Create Jira tickets
    jira_server = validate_jira_connection()
    if jira_server is None:
        logging.error("Failed to connect to Jira. Skipping ticket creation.")
        print("Failed to connect to Jira. Skipping ticket creation.")
        return
    else:
        ticket_keys = create_jira_tickets(jira_server, tasks)
        print("\nTicket keys: ", [tk['key'] for tk in ticket_keys])

if __name__ == "__main__":
    main()