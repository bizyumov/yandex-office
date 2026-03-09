#!/usr/bin/env python3
"""
Yandex Tracker API Client

Core API client for Yandex Tracker integration.
Supports both Yandex 360 and Yandex Cloud organizations.
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional, Dict, List, Any, Union
from urllib.parse import urljoin

import requests


class TrackerError(Exception):
    """Base exception for Tracker API errors."""
    pass


class TrackerAuthError(TrackerError):
    """Authentication error."""
    pass


class TrackerNotFoundError(TrackerError):
    """Resource not found."""
    pass


class TrackerValidationError(TrackerError):
    """Validation error."""
    pass


class TrackerClient:
    """Yandex Tracker API client."""
    
    BASE_URL = "https://api.tracker.yandex.net/v3"
    
    def __init__(self, token: str, org_id: str, org_type: str = "360"):
        """
        Initialize client.
        
        Args:
            token: OAuth or IAM token
            org_id: Organization ID
            org_type: "360" or "cloud"
        """
        self.token = token
        self.org_id = org_id
        self.org_type = org_type
        
        self.session = requests.Session()
        
        # Set auth header based on token type
        # OAuth tokens start with y0_
        if token.startswith("y0_"):
            self.session.headers["Authorization"] = f"OAuth {token}"
        else:
            self.session.headers["Authorization"] = f"Bearer {token}"
        
        # Set org header
        if org_type == "cloud":
            self.session.headers["X-Cloud-Org-ID"] = org_id
        else:
            self.session.headers["X-Org-ID"] = org_id
    
    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> Any:
        """Make API request with error handling."""
        url = urljoin(self.BASE_URL, endpoint)
        
        try:
            response = self.session.request(method, url, **kwargs)
            
            if response.status_code == 401:
                raise TrackerAuthError("Invalid or expired token")
            elif response.status_code == 403:
                raise TrackerAuthError("Access denied - check permissions")
            elif response.status_code == 404:
                raise TrackerNotFoundError(f"Resource not found: {endpoint}")
            elif response.status_code == 409:
                raise TrackerError(f"Conflict: {response.text}")
            elif response.status_code == 422:
                raise TrackerValidationError(f"Validation error: {response.text}")
            elif response.status_code >= 400:
                raise TrackerError(f"API error {response.status_code}: {response.text}")
            
            if response.status_code == 204:
                return None
            
            return response.json()
            
        except requests.RequestException as e:
            raise TrackerError(f"Request failed: {e}")
    
    # User methods
    
    def get_myself(self) -> Dict[str, Any]:
        """Get current user info."""
        return self._request("GET", "/myself")
    
    # Issue search methods
    
    def search_issues(
        self,
        query: Optional[str] = None,
        filter_obj: Optional[Dict] = None,
        queue: Optional[str] = None,
        keys: Optional[List[str]] = None,
        order: Optional[str] = None,
        expand: Optional[List[str]] = None,
        per_page: int = 50,
        page: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Search issues using query language or filters.
        
        Args:
            query: Query language string
            filter_obj: Filter object (dict)
            queue: Queue key (shortcut)
            keys: List of issue keys
            order: Sort order (e.g., "+createdAt" or "-updatedAt")
            expand: Additional fields to include
            per_page: Results per page
            page: Page number
            
        Returns:
            List of issue objects
        """
        params = {}
        if expand:
            params["expand"] = ",".join(expand)
        if per_page:
            params["perPage"] = per_page
        if page:
            params["page"] = page
        
        body: Dict[str, Any] = {}
        
        if queue:
            body["queue"] = queue
        elif keys:
            body["keys"] = keys
        elif filter_obj:
            body["filter"] = filter_obj
            if order:
                body["order"] = order
        elif query:
            body["query"] = query
        else:
            raise ValueError("One of query, filter_obj, queue, or keys required")
        
        return self._request("POST", "/issues/_search", params=params, json=body)
    
    # Issue CRUD methods
    
    def get_issue(self, issue_key: str, expand: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Get issue by key.
        
        Args:
            issue_key: Issue key (e.g., "PROJ-123")
            expand: Additional fields (transitions, attachments, comments)
            
        Returns:
            Issue object
        """
        params = {}
        if expand:
            params["expand"] = ",".join(expand)
        
        return self._request("GET", f"/issues/{issue_key}", params=params)
    
    def create_issue(
        self,
        queue: str,
        summary: str,
        description: Optional[str] = None,
        issue_type: str = "task",
        priority: Optional[str] = None,
        assignee: Optional[str] = None,
        followers: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        due_date: Optional[str] = None,
        parent: Optional[str] = None,
        **custom_fields
    ) -> Dict[str, Any]:
        """
        Create a new issue.
        
        Args:
            queue: Queue key
            summary: Issue title
            description: Issue description
            issue_type: Issue type (task, bug, etc.)
            priority: Priority (critical, high, normal, low)
            assignee: Assignee login or "me()"
            followers: List of follower logins
            tags: List of tags
            due_date: Due date (YYYY-MM-DD)
            parent: Parent issue key for subtasks
            **custom_fields: Additional custom fields
            
        Returns:
            Created issue object
        """
        body: Dict[str, Any] = {
            "queue": queue,
            "summary": summary,
            "type": issue_type
        }
        
        if description:
            body["description"] = description
        if priority:
            body["priority"] = priority
        if assignee:
            body["assignee"] = assignee
        if followers:
            body["followers"] = followers
        if tags:
            body["tags"] = tags
        if due_date:
            body["dueDate"] = due_date
        if parent:
            body["parent"] = parent
        
        # Add custom fields
        body.update(custom_fields)
        
        return self._request("POST", "/issues", json=body)
    
    def update_issue(
        self,
        issue_key: str,
        summary: Optional[str] = None,
        description: Optional[str] = None,
        priority: Optional[str] = None,
        assignee: Optional[str] = None,
        due_date: Optional[str] = None,
        add_tags: Optional[List[str]] = None,
        remove_tags: Optional[List[str]] = None,
        **custom_fields
    ) -> Dict[str, Any]:
        """
        Update issue fields.
        
        Args:
            issue_key: Issue key
            summary: New title
            description: New description
            priority: New priority
            assignee: New assignee (login, "me()", or "empty()")
            due_date: New due date
            add_tags: Tags to add
            remove_tags: Tags to remove
            **custom_fields: Additional fields
            
        Returns:
            Updated issue object
        """
        body: Dict[str, Any] = {}
        
        if summary:
            body["summary"] = summary
        if description:
            body["description"] = description
        if priority:
            body["priority"] = priority
        if assignee:
            body["assignee"] = assignee
        if due_date:
            body["dueDate"] = due_date
        if add_tags:
            body["tags"] = {"add": add_tags}
        if remove_tags:
            if "tags" not in body:
                body["tags"] = {}
            body["tags"]["remove"] = remove_tags
        
        body.update(custom_fields)
        
        return self._request("PATCH", f"/issues/{issue_key}", json=body)
    
    def transition_issue(
        self,
        issue_key: str,
        transition_id: str,
        resolution: Optional[str] = None,
        comment: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute workflow transition.
        
        Args:
            issue_key: Issue key
            transition_id: Transition ID
            resolution: Resolution for closing transitions
            comment: Comment to add
            
        Returns:
            Updated issue object
        """
        body: Dict[str, Any] = {}
        
        if resolution:
            body["resolution"] = resolution
        if comment:
            body["comment"] = comment
        
        return self._request(
            "POST",
            f"/issues/{issue_key}/transitions/{transition_id}/_execute",
            json=body
        )
    
    # Comment methods
    
    def add_comment(
        self,
        issue_key: str,
        text: str,
        summon: Optional[List[str]] = None,
        add_to_followers: bool = True,
        attachment_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Add comment to issue.
        
        Args:
            issue_key: Issue key
            text: Comment text (supports YFM markdown)
            summon: List of logins to mention
            add_to_followers: Add self to followers
            attachment_ids: Temporary attachment IDs
            
        Returns:
            Comment object
        """
        body: Dict[str, Any] = {
            "text": text,
            "isAddToFollowers": add_to_followers
        }
        
        if summon:
            body["summonees"] = summon
        if attachment_ids:
            body["attachmentIds"] = attachment_ids
        
        return self._request("POST", f"/issues/{issue_key}/comments", json=body)
    
    def get_comments(self, issue_key: str) -> List[Dict[str, Any]]:
        """Get all comments for an issue."""
        return self._request("GET", f"/issues/{issue_key}/comments")
    
    # Board methods
    
    def get_boards(self) -> List[Dict[str, Any]]:
        """Get all accessible boards."""
        return self._request("GET", "/boards")
    
    def get_board(self, board_id: int) -> Dict[str, Any]:
        """
        Get board details with columns and issues.
        
        Args:
            board_id: Board ID
            
        Returns:
            Board object with columns
        """
        return self._request("GET", f"/boards/{board_id}")
    
    # Queue methods
    
    def get_queues(self) -> List[Dict[str, Any]]:
        """Get all accessible queues."""
        return self._request("GET", "/queues")
    
    def get_queue(self, queue_key: str) -> Dict[str, Any]:
        """Get queue info."""
        return self._request("GET", f"/queues/{queue_key}")


def load_tracker_client(account: str, config_path: Optional[str] = None) -> TrackerClient:
    """
    Load tracker client from config and token file.
    
    Args:
        account: Account name (token file name)
        config_path: Path to config.json (auto-discovered if not provided)
        
    Returns:
        Configured TrackerClient instance
    """
    # Find config
    if config_path:
        config_file = Path(config_path)
    else:
        # Walk up from current directory
        current = Path.cwd()
        config_file = None
        for parent in [current] + list(current.parents):
            candidate = parent / "config.json"
            if candidate.exists():
                config_file = candidate
                break
        
        if not config_file:
            raise TrackerError("config.json not found")
    
    with open(config_file) as f:
        config = json.load(f)
    
    # Determine data directory
    data_dir = Path(config_file).parent / config.get("data_dir", "../../yandex-data")
    data_dir = data_dir.resolve()
    
    # Load token
    token_file = data_dir / "auth" / f"{account}.token"
    if not token_file.exists():
        raise TrackerError(f"Token file not found: {token_file}")
    
    with open(token_file) as f:
        token_data = json.load(f)
    
    token = token_data.get("token.tracker")
    if not token:
        raise TrackerError(f"No tracker token for account {account}")
    
    org_id = token_data.get("org_id")
    if not org_id:
        raise TrackerError(f"No org_id for account {account}")
    
    org_type = token_data.get("org_type", "360")
    
    return TrackerClient(token=token, org_id=org_id, org_type=org_type)


if __name__ == "__main__":
    # Simple test
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Tracker API connection")
    parser.add_argument("--account", required=True, help="Account name")
    parser.add_argument("--config", help="Path to config.json")
    
    args = parser.parse_args()
    
    try:
        client = load_tracker_client(args.account, args.config)
        myself = client.get_myself()
        print(f"Connected as: {myself.get('display', 'Unknown')}")
        print(f"UID: {myself.get('passportUid')}")
    except TrackerError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
