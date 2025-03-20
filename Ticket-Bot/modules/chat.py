class ChatHistory:
    def __init__(self, max_history=5):
        self.max_history = max_history
        self.messages = []
        self.conversation_pairs = []
        self.user_details = None
        self.problem_summary = None
        self.awaiting_satisfaction = False
        # Pre-chat form fields
        self.name = None
        self.email = None
        self.phone_number = None
        self.issue_description = None  # Small Description of the Issue/Request
        # Workflow fields
        self.customer = None  # Customer Name (e.g., Wheeltek)
        self.product = None   # Product Name (e.g., LOS)
        self.state = "pre_chat"  # Tracks workflow state: pre_chat, identify_issue, customer_product, specific_issue, request_handling, complete
        self.specific_data = {}  # Stores additional data (e.g., Application ID, Screenshot request)

    def add_message(self, role, content):
        self.messages.append({"role": role, "content": content})
        if role == "user":
            self._current_query = content
            self._process_user_input(content)
        elif role == "assistant" and hasattr(self, '_current_query'):
            self.conversation_pairs.append((self._current_query, content))
            self._maintain_history_window()

    def _maintain_history_window(self):
        if len(self.conversation_pairs) > self.max_history:
            self.conversation_pairs = self.conversation_pairs[-self.max_history:]

    def _process_user_input(self, content):
        content_lower = content.lower()
        if self.state == "pre_chat":
            if not self.name:
                self.name = content.strip()
            elif not self.email:
                self.email = content.strip() if "@" in content else None
            elif not self.phone_number:
                self.phone_number = content.strip() if content.replace("+", "").replace("-", "").replace(" ", "").isdigit() else None
            elif not self.issue_description:
                self.issue_description = content.strip()
                self.state = "identify_issue"
        elif self.state == "identify_issue":
            self.issue_description = content.strip()
            self.state = "customer_product"
        elif self.state == "customer_product":
            if not self.customer:
                valid_customers = ["wheeltek", "celestina", "new nemar", "mazda", "motorace", "first valley bank"]
                self.customer = next((c for c in valid_customers if c in content_lower), content.strip())
            elif not self.product:
                valid_products = ["los", "aidc", "up", "denali", "imd", "alps", "autotech – msc"]
                self.product = next((p for p in valid_products if p in content_lower), content.strip())
                self.state = "specific_issue" if "issue" in self.issue_description.lower() else "request_handling"
        elif self.state == "specific_issue":
            self._handle_specific_issue(content)
        elif self.state == "request_handling":
            self._handle_request(content)

    def _handle_specific_issue(self, content):
        content_lower = content.lower()
        if self.product == "los" and "application_id" not in self.specific_data:
            self.specific_data["application_id"] = content.strip()
            self.state = "complete"  # Move to complete state after collecting Application ID
        elif "login issue" in self.issue_description.lower() and "screenshot" not in self.specific_data:
            self.specific_data["screenshot"] = content.strip()
            self.state = "complete"
        elif "auto logout" in self.issue_description.lower():
            if "screen_recording" not in self.specific_data:
                self.specific_data["screen_recording"] = content.strip() if "yes" in content_lower else "No"
            elif "module" not in self.specific_data:
                self.specific_data["module"] = content.strip()
                self.state = "complete"
        elif "payment issue" in self.issue_description.lower() and "receipt_number" not in self.specific_data:
            self.specific_data["receipt_number"] = content.strip()
            self.state = "complete"
        elif "tpin issue" in self.issue_description.lower() and "tpin_number" not in self.specific_data:
            self.specific_data["tpin_number"] = content.strip()
            self.state = "complete"
        elif "allocation" in self.issue_description.lower():
            if "screenshot" not in self.specific_data:
                self.specific_data["screenshot"] = content.strip()
            elif "collection_specialist" not in self.specific_data:
                self.specific_data["collection_specialist"] = {"full_name": content.strip()}
            elif "username" not in self.specific_data["collection_specialist"]:
                self.specific_data["collection_specialist"]["username"] = content.strip()
            elif "contact_number" not in self.specific_data["collection_specialist"]:
                self.specific_data["collection_specialist"]["contact_number"] = content.strip()
                self.state = "complete"
        elif self.product == "denali" and "login issue" in self.issue_description.lower():
            if "ebt_name" not in self.specific_data:
                self.specific_data["ebt_name"] = content.strip()
            elif "branch_role" not in self.specific_data:
                self.specific_data["branch_role"] = content.strip()
            elif "screenshot" not in self.specific_data:
                self.specific_data["screenshot"] = content.strip()
                self.state = "complete"

    def _handle_request(self, content):
        content_lower = content.lower()
        if "new user" in self.issue_description.lower():
            if "employee_id" not in self.specific_data:
                self.specific_data["employee_id"] = content.strip()
            elif "full_name" not in self.specific_data:
                self.specific_data["full_name"] = content.strip()
            elif "contact_number" not in self.specific_data:
                self.specific_data["contact_number"] = content.strip()
            elif "email_id" not in self.specific_data:
                self.specific_data["email_id"] = content.strip()
            elif "role" not in self.specific_data:
                self.specific_data["role"] = content.strip()
            elif "branch" not in self.specific_data:
                self.specific_data["branch"] = content.strip()
                self.state = "complete"
        elif "contact number change" in self.issue_description.lower() and "new_number" not in self.specific_data:
            self.specific_data["new_number"] = content.strip()
            self.state = "complete"
        elif "password reset" in self.issue_description.lower():
            if "tried_forgot_password" not in self.specific_data:
                self.specific_data["tried_forgot_password"] = content.strip()
            elif "screenshot" not in self.specific_data and "no" in self.specific_data["tried_forgot_password"].lower():
                self.specific_data["screenshot"] = content.strip()
                self.state = "complete"
        elif "module" in self.issue_description.lower():
            if "branch" not in self.specific_data:
                self.specific_data["branch"] = content.strip()
            elif "role" not in self.specific_data:
                self.specific_data["role"] = content.strip()
                self.state = "complete"

    def get_messages(self):
        return self.messages

    def get_conversation_pairs(self):
        return self.conversation_pairs

    def clear_history(self):
        self.messages.clear()
        self.conversation_pairs.clear()