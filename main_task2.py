import os
import re
import json
import logging
import base64
from datetime import datetime
from github import Github
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
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_USERNAME = os.getenv('GITHUB_USERNAME')
GITHUB_REPO = os.getenv('GITHUB_REPO')
PROJECT_NAME = os.getenv('PROJECT_NAME', 'Body Guard Booking System')
PROJECT_DESCRIPTION = os.getenv('PROJECT_DESCRIPTION', 'A platform for booking bodyguard and security services with user, guard, and admin functionalities')

def read_ticket_keys(file_path):
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

def create_github_repo():
    try:
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        repo = user.create_repo(
            GITHUB_REPO,
            description=PROJECT_DESCRIPTION,
            private=False,
            auto_init=True
        )
        logging.info(f"Created repository: {repo.html_url}")
        print(f"Created repository: {repo.html_url}")
        return repo
    except Exception as e:
        logging.warning(f"Error creating repository: {e}")
        print(f"Error creating repository: {e}")
        try:
            repo = user.get_repo(GITHUB_REPO)
            logging.info(f"Repository already exists: {repo.html_url}")
            print(f"Repository already exists: {repo.html_url}")
            return repo
        except:
            logging.error("Failed to access existing repository.")
            print("Failed to access existing repository.")
            return None

def initialize_repo(repo, ticket_keys):
    try:
        # Initialize files
        files = {
            'main_task1.py': {
                'content': "# Task: Jira Ticket Creation and Management\n\n# Implementation for Body Guard Booking System\n",
                'type': 'text'
            },
            'main_task2.py': {
                'content': "# Task: GitHub Repository Creation and Structuring\n\n# Implementation for repository setup\n",
                'type': 'text'
            },
            'main_task3.py': {
                'content': "# Task: Test Case Generation\n\n# Implementation for generating test cases using Groq API\n",
                'type': 'text'
            },
            'requirements.txt': {
                'content': "requests\npygithub\npython-dotenv\ngroq\npython-jira\npython-docx\nPyPDF2\n",
                'type': 'text'
            }
        }

        for file_path, file_info in files.items():
            content = file_info['content']
            content_type = file_info['type']

            if os.path.exists(file_path):
                if content_type == 'text':
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                else:
                    with open(file_path, 'rb') as f:
                        content = f.read()
                logging.info(f"Found local file {file_path}")
            else:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                logging.info(f"Created placeholder file {file_path}")

            try:
                contents = repo.get_contents(file_path, ref="main")
                if content_type == 'text':
                    repo.update_file(
                        file_path,
                        f"Update {file_path} from project",
                        content,
                        contents.sha,
                        branch="main"
                    )
                else:
                    repo.update_file(
                        file_path,
                        f"Update {file_path} from project",
                        base64.b64encode(content).decode('utf-8'),
                        contents.sha,
                        branch="main"
                    )
                logging.info(f"Updated {file_path} in repository")
                print(f"Updated {file_path} in repository")
            except:
                if content_type == 'text':
                    repo.create_file(
                        file_path,
                        f"Add {file_path} from project",
                        content,
                        branch="main"
                    )
                else:
                    repo.create_file(
                        file_path,
                        f"Add {file_path} from project",
                        base64.b64encode(content).decode('utf-8'),
                        branch="main"
                    )
                logging.info(f"Added {file_path} to repository")
                print(f"Added {file_path} to repository")

        # Organize tasks and subtasks from ticket_keys
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

        # Generate main README.md
        readme_content = (
            f"# {PROJECT_NAME}\n\n"
            f"## Overview\n"
            f"{PROJECT_DESCRIPTION}\n\n"
            f"## Tasks\n"
        )

        for task_key, task_info in tasks.items():
            readme_content += (
                f"### {task_key}: {task_info['summary']}\n"
                f"#### Description\n{task_info['description']}\n\n"
                f"#### Acceptance Criteria\n"
            )
            if task_info['acceptance_criteria']:
                readme_content += "\n".join([f"- {crit}" for crit in task_info['acceptance_criteria']]) + "\n"
            else:
                readme_content += "- None provided.\n"

            if task_info['subtasks']:
                readme_content += "\n#### Subtasks\n"
                for subtask_key, subtask in task_info['subtasks'].items():
                    readme_content += (
                        f"##### {subtask_key}: {subtask['summary']}\n"
                        f"###### Description\n{subtask['description']}\n\n"
                        f"###### Acceptance Criteria\n"
                    )
                    if subtask['acceptance_criteria']:
                        readme_content += "\n".join([f"- {crit}" for crit in subtask['acceptance_criteria']]) + "\n"
                    else:
                        readme_content += "- None provided.\n"
                    readme_content += "\n"

        try:
            contents = repo.get_contents("README.md", ref="main")
            repo.update_file(
                "README.md",
                "Update README.md",
                readme_content,
                contents.sha,
                branch="main"
            )
            logging.info("Updated README.md in repository")
            print("Updated README.md in repository")
        except:
            repo.create_file(
                "README.md",
                "Add README.md",
                readme_content,
                branch="main"
            )
            logging.info("Added README.md to repository")
            print("Added README.md to repository")
    except Exception as e:
        logging.error(f"Error initializing repository: {e}")
        print(f"Error: Failed to initialize repository: {e}")

def create_branches(repo, ticket_keys):
    try:
        # Organize tasks and subtasks from ticket_keys
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

        # Create branches for tasks
        for task_key, task in tasks.items():
            sanitized_summary = re.sub(r'[^a-zA-Z0-9\s-]', '', task['summary']).lower().replace(' ', '-')
            branch_name = f"feature/{task_key}-{sanitized_summary}"[:50]

            source_branch = repo.get_branch("main")
            repo.create_git_ref(
                ref=f"refs/heads/{branch_name}",
                sha=source_branch.commit.sha
            )
            logging.info(f"Created branch: {branch_name}")
            print(f"Created branch: {branch_name}")

            # Generate README for branch
            readme_content = f"# {task_key}: {task['summary']}\n\n"
            readme_content += f"## Description\n{task['description']}\n\n"
            readme_content += "## Acceptance Criteria\n"
            if task['acceptance_criteria']:
                readme_content += "\n".join([f"- {crit}" for crit in task['acceptance_criteria']]) + "\n"
            else:
                readme_content += "- None\n"
            readme_content += "\n"

            if task['subtasks']:
                readme_content += "## Subtasks\n"
                for subtask_key, subtask in task['subtasks'].items():
                    readme_content += f"### {subtask_key}: {subtask['summary']}\n"
                    readme_content += f"#### Description\n{subtask['description']}\n\n"
                    readme_content += "#### Acceptance Criteria\n"
                    if subtask['acceptance_criteria']:
                        readme_content += "\n".join([f"- {crit}" for crit in subtask['acceptance_criteria']]) + "\n"
                    else:
                        readme_content += "- None\n"
                    readme_content += "\n"

            try:
                contents = repo.get_contents("README.md", ref=branch_name)
                repo.update_file(
                    "README.md",
                    f"Update README.md for {task_key}",
                    readme_content,
                    contents.sha,
                    branch=branch_name
                )
                logging.info(f"Updated README.md in branch {branch_name}")
                print(f"Updated README.md in branch {branch_name}")
            except:
                repo.create_file(
                    "README.md",
                    f"Add README.md for {task_key}",
                    readme_content,
                    branch=branch_name
                )
                logging.info(f"Added README.md to branch {branch_name}")
                print(f"Added README.md to branch {branch_name}")

    except Exception as e:
        logging.error(f"Error creating branches: {e}")
        print(f"Error creating branches: {e}")

def main():
    ticket_keys = read_ticket_keys('ticket_keys.json')
    if not ticket_keys:
        logging.error("No ticket keys found.")
        print("No ticket keys found.")
        return

    repo = create_github_repo()
    if not repo:
        logging.error("Failed to create or access repository.")
        print("Failed to create or access repository.")
        return

    initialize_repo(repo, ticket_keys)
    create_branches(repo, ticket_keys)
    logging.info(f"Repository setup completed: https://github.com/{GITHUB_USERNAME}/{GITHUB_REPO}")
    print(f"Repository setup completed successfully: https://github.com/{GITHUB_USERNAME}/{GITHUB_REPO}")

if __name__ == '__main__':
    main()