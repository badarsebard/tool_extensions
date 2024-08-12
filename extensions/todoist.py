import json
import uuid

import requests

from todoist_api_python.api import TodoistAPI
from todoist_api_python.endpoints import get_sync_url
from todoist_api_python.http_requests import get, post
from todoist_api_python.models import Task


class Api(TodoistAPI):
    def __init__(self, token: str) -> None:
        super().__init__(token)

    def get_sync_task(self, task_id: str) -> Task:
        endpoint = get_sync_url("items/get")
        task = post(
            self._session,
            endpoint,
            self._token,
            data={"item_id": task_id, "all_data": False},
        )
        return Task.from_dict(task["item"])

    def move_task(self, task_id, project_id=None, section_id=None, parent_id=None):
        if sum(x is not None for x in [project_id, section_id, parent_id]) != 1:
            raise ValueError(
                "Exactly one of project_id, section_id, or parent_id must be provided."
            )
        args = {
            "id": task_id,
        }
        for target_name, target_id in [
            ("project_id", project_id),
            ("section_id", section_id),
            ("parent_id", parent_id),
        ]:
            if target_id is not None:
                args[target_name] = target_id
        endpoint = get_sync_url("sync")
        params = {
            "commands": json.dumps(
                [
                    {
                        "type": "item_move",
                        "uuid": uuid.uuid4().hex,
                        "args": args,
                    }
                ]
            )
        }
        headers = {
            "Authorization": f"Bearer {self._token}",
        }
        return self._session.post(endpoint, headers=headers, params=params)

    def sync(self, resource_types, sync_token="*"):
        if sync_token is None:
            sync_token = "*"
        endpoint = get_sync_url("sync")
        data = {
            "resource_types": resource_types,
            "sync_token": sync_token,
        }
        return post(self._session, endpoint, self._token, data=data)
