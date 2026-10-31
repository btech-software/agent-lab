import json
import os
from abc import ABC
from urllib.parse import quote

import requests
from langchain_core.tools import tool, BaseTool
from msal import ConfidentialClientApplication
from typing_extensions import Annotated

from agent_lab.services.agent_types.base import AgentUtils, ContactSupportAgentBase


class AzureEntraIdOrganizationWorkflowBase(ContactSupportAgentBase, ABC):
    def __init__(self, agent_utils: AgentUtils):
        super().__init__(agent_utils)

    def get_token(self) -> str:
        client_id = os.getenv("AZURE_CLIENT_ID")
        client_secret = os.getenv("AZURE_CLIENT_SECRET")
        tenant_id = os.getenv("AZURE_TENANT_ID")
        app = ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )
        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" in result:
            return result["access_token"]
        else:
            self.logger.error("Could not obtain Azure access token")
            return ""

    def get_person_search_tool(self) -> BaseTool:
        @tool("person_search")
        def person_search_tool_call(
            name: Annotated[str, "The name of the person for search."],
        ):
            """
            "Use this tool to search for individuals within the domain or organization. "
            "It is particularly useful for looking up co-workers' profiles, such as their roles, departments, or contact information. "
            "For example, you can search for 'John Doe' to retrieve relevant details about their position and team."
            """
            headers = {"Authorization": f"Bearer {self.get_token()}"}
            # OData string literal: escape ' by doubling; requests URL-encodes params
            odata_name = name.replace("'", "''")
            response = requests.get(
                "https://graph.microsoft.com/v1.0/users",
                params={"$filter": f"startswith(displayName,'{odata_name}')"},
                headers=headers,
            )
            if response.status_code == 200:
                users = response.json().get("value", [])
                if users:
                    result = [
                        f"{user['displayName']} ({user['userPrincipalName']})"
                        for user in users
                    ]
                    return "\n".join(result)
                else:
                    return "No users found"
            else:
                return f"Error: {response.status_code} - {response.text}"

        return person_search_tool_call

    def get_person_details_tool(self) -> BaseTool:
        @tool("person_details")
        def person_details_tool_call(email: Annotated[str, "The email of the person."]):
            """
            "Use this tool to retrieve detailed information about a person using their email address as a parameter. "
            "For instance, providing 'jane.doe@example.com' will return details such as their full name, job title, and organizational affiliation."
            """
            headers = {"Authorization": f"Bearer {self.get_token()}"}
            url = f"https://graph.microsoft.com/v1.0/users/{quote(email, safe='@')}"
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                user = response.json()
                return json.dumps(user)
            elif response.status_code == 404:
                return "User not found"
            else:
                return f"Error: {response.status_code} - {response.text}"

        return person_details_tool_call
