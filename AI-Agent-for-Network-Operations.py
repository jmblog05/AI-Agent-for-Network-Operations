import os
from typing import TypedDict, Any

import requests
from netmiko import ConnectHandler
from google import genai
from langgraph.graph import StateGraph, START, END


# ============================================================
# Configuration
# ============================================================

ZABBIX_URL = "http://172.16.1.3:8080/api_jsonrpc.php"

CISCO_USER = os.environ["CISCO_user"]
CISCO_PASSWORD = os.environ["CISCO_password"]
ZABBIX_USER = os.environ["Zabbix_user"]
ZABBIX_PASSWORD = os.environ["Zabbix_password"]
GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]

client = genai.Client(api_key=GOOGLE_API_KEY)


# Cisco commands allowed for execution
allowed_commands = [
    "show run",
    "show ip int brief",
    "show ip ospf nei",
    "show ip bgp summary",
    "show ip route",
    "show logging",
]


# ============================================================
# State shared by LangGraph
# ============================================================

class AgentState(TypedDict, total=False):
    user_message: str
    problems: list[dict[str, Any]]

    # ★ Store multiple devices, not just one
    target_ips: list[str]
    target_hosts: list[str]

    cli_outputs: list[str]
    extra_commands: list[str]
    investigation_count: int
    need_more: bool
    answer: str


# ============================================================
# Zabbix
# ============================================================

def get_zabbix_problems():

    # -------------------------
    # Login
    # -------------------------

    login_payload = {
        "jsonrpc": "2.0",
        "method": "user.login",
        "params": {
            "username": ZABBIX_USER,
            "password": ZABBIX_PASSWORD
        },
        "id": 1
    }

    response = requests.post(
        ZABBIX_URL,
        json=login_payload
    )

    response.raise_for_status()

    auth_token = response.json()["result"]

    headers = {
        "Content-Type": "application/json-rpc",
        "Authorization": f"Bearer {auth_token}"
    }

    # -------------------------
    # Retrieve Problems
    # -------------------------

    problem_payload = {
        "jsonrpc": "2.0",
        "method": "problem.get",
        "params": {
            "output": "extend",
            "sortfield": "eventid",
            "sortorder": "DESC"
        },
        "id": 2
    }

    response = requests.post(
        ZABBIX_URL,
        json=problem_payload,
        headers=headers
    )

    response.raise_for_status()

    problems = response.json()["result"]

    # -------------------------
    # Problem → Trigger → Host
    # -------------------------

    for problem in problems:

        trigger_id = problem["objectid"]

        trigger_payload = {
            "jsonrpc": "2.0",
            "method": "trigger.get",
            "params": {
                "triggerids": trigger_id,
                "output": ["triggerid", "description"],
                "selectHosts": ["hostid", "host", "name"]
            },
            "id": 3
        }

        response = requests.post(
            ZABBIX_URL,
            json=trigger_payload,
            headers=headers
        )

        response.raise_for_status()

        triggers = response.json()["result"]

        if not triggers or not triggers[0].get("hosts"):
            continue

        host = triggers[0]["hosts"][0]
        hostid = host["hostid"]

        # -------------------------
        # Host → Interface
        # -------------------------

        host_payload = {
            "jsonrpc": "2.0",
            "method": "host.get",
            "params": {
                "hostids": hostid,
                "output": ["hostid", "host", "name"],
                "selectInterfaces": [
                    "interfaceid",
                    "ip",
                    "dns",
                    "main",
                    "type"
                ]
            },
            "id": 4
        }

        response = requests.post(
            ZABBIX_URL,
            json=host_payload,
            headers=headers
        )

        response.raise_for_status()

        hosts = response.json()["result"]

        if not hosts or not hosts[0].get("interfaces"):
            continue

        interface = hosts[0]["interfaces"][0]

        problem["hostname"] = host["name"]
        problem["ip"] = interface["ip"]

    # -------------------------
    # Keep only the information needed by the LLM
    # -------------------------

    simplified_problems = []

    for problem in problems:

        if "hostname" not in problem or "ip" not in problem:
            continue

        simplified_problems.append({
            "eventid": problem["eventid"],
            "name": problem["name"],
            "severity": problem["severity"],
            "clock": problem["clock"],
            "hostname": problem["hostname"],
            "ip": problem["ip"]
        })

    return simplified_problems


# ============================================================
# Cisco CLI
# ============================================================

def get_cisco_cli(ips, commands):

    # ★ Store CLI output from all devices
    all_outputs = []

    # --------------------------------------------------------
    # Execute only allowed commands
    # --------------------------------------------------------

    for command in commands:

        if command not in allowed_commands:

            return [
                f"Command is not allowed: {command}"
            ]

    # --------------------------------------------------------
    # ★ Process each IP address one at a time
    # --------------------------------------------------------

    for ip in ips:

        print("[ssh] Target:", ip)
        print("[ssh] Commands:", commands)

        connection = None

        try:

            device = {
                "device_type": "cisco_ios",
                "host": ip,
                "username": CISCO_USER,
                "password": CISCO_PASSWORD,
                "secret": CISCO_PASSWORD,
            }

            connection = ConnectHandler(**device)

            connection.enable()

            # CLI output for this device
            output_list = []

            for command in commands:

                output = connection.send_command(command)

                output_list.append(
                    f"===== {ip} : {command} =====\n{output}"
                )

            # Add to the results from all devices
            all_outputs.extend(output_list)

        except Exception as e:

            # ★ Do not stop the entire process if SSH fails for one device

            print(
                "[ssh] SSH connection failed:",
                e
            )

            all_outputs.append(
                f"===== {ip} : SSH connection failed =====\n"
                f"{e}"
            )

        finally:

            if connection is not None:

                try:
                    connection.disconnect()
                except Exception:
                    pass

    return all_outputs


# ============================================================
# Node 1: conversation
# ============================================================

def conversation_node(state: AgentState):

    print("\n[conversation]")
    print("User inquiry:", state["user_message"])

    return {
        "investigation_count": 0,
        "cli_outputs": [],
        "extra_commands": []
    }


# ============================================================
# Node 2: zabbix
# ============================================================

def zabbix_node(state: AgentState):

    print("[zabbix] Retrieving problems from Zabbix")

    problems = get_zabbix_problems()

    if not problems:

        return {
            "problems": [],
            "need_more": False,
            "answer": "Could not retrieve current problems from Zabbix."
        }

    # ========================================================
    # ★ Collect target IP addresses from all problems
    # ========================================================

    target_ips = []
    target_hosts = []

    for problem in problems:

        ip = problem["ip"]
        hostname = problem["hostname"]

        print(
            "[zabbix] Target:",
            hostname,
            ip
        )

        print(
            "[zabbix] Problem:",
            problem["name"]
        )

        # If a device has multiple problems,
        # group them into a single SSH investigation
        if ip not in target_ips:

            target_ips.append(ip)
            target_hosts.append(hostname)

    return {
        "problems": problems,
        "target_ips": target_ips,
        "target_hosts": target_hosts
    }


# ============================================================
# Node 3: ssh
# ============================================================

def ssh_node(state: AgentState):

    count = state.get(
        "investigation_count",
        0
    )

    if count == 0:

        # Initial investigation
        commands = [
            "show ip int brief",
            "show ip ospf nei",
            "show ip bgp summary"
        ]

    else:

        # Additional investigation
        commands = state.get(
            "extra_commands",
            ["show logging"]
        )

    # ========================================================
    # ★ Pass multiple IP addresses to get_cisco_cli
    # ========================================================

    outputs = get_cisco_cli(
        state["target_ips"],
        commands
    )

    return {
        "cli_outputs": state.get(
            "cli_outputs",
            []
        ) + outputs,

        "investigation_count": count + 1
    }


# ============================================================
# Node 4: Is additional investigation needed?
# ============================================================

def check_more_node(state: AgentState):

    print("[check] Asking the AI whether additional investigation is needed")

    cli_output = "\n\n".join(
        state.get("cli_outputs", [])
    )

    prompt = f"""
You are an AI assistant for network operations.

User inquiry:
{state["user_message"]}

Problems detected by Zabbix:
{state.get("problems", [])}

Cisco CLI output:
{cli_output}

Determine whether the available information is sufficient to explain the cause or status of the network issue.

If additional Cisco CLI investigation is needed, respond with Yes.
If the issue can be explained using the available information, respond with No.

Return only Yes or No.
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    result = response.text.strip()

    need_more = result.lower().startswith("yes")

    # In v1, allow a maximum of one additional investigation
    if state.get("investigation_count", 0) >= 2:

        need_more = False

    print(
        "[check] AI decision:",
        result
    )

    if need_more:

        return {
            "need_more": True,
            "extra_commands": [
                "show logging"
            ]
        }

    return {
        "need_more": False
    }


# ============================================================
# Node 5: Answer
# ============================================================

def answer_node(state: AgentState):

    print("[answer] Generating the final response")

    cli_output = "\n\n".join(
        state.get("cli_outputs", [])
    )

    prompt = f"""
You are an AI assistant for network operations.

User inquiry:
{state["user_message"]}

Problems detected by Zabbix:
{state.get("problems", [])}

Information retrieved from Cisco devices:

{cli_output}

Using only the information above, provide a clear explanation in English.

Address the following points:

- Problems detected by Zabbix
- Current status of the Cisco devices
- Possible causes of the network issue
- Additional checks that may be useful

If multiple Cisco devices are experiencing problems,
explain each device’s issue separately.

Also consider whether an issue on one device could affect
connectivity, SSH, or ICMP reachability to another device.
Explain this when it can be inferred from the CLI output and network topology.

Describe conclusions that cannot be confirmed from the available information as possibilities rather than facts.
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    return {
        "answer": response.text
    }


# ============================================================
# LangGraph
# ============================================================

builder = StateGraph(AgentState)

builder.add_node(
    "conversation",
    conversation_node
)

builder.add_node(
    "zabbix",
    zabbix_node
)

builder.add_node(
    "ssh",
    ssh_node
)

builder.add_node(
    "check_more",
    check_more_node
)

builder.add_node(
    "answer",
    answer_node
)


# ============================================================
# START
# ============================================================

builder.add_edge(
    START,
    "conversation"
)


# conversation → zabbix

builder.add_edge(
    "conversation",
    "zabbix"
)


# zabbix → ssh

builder.add_edge(
    "zabbix",
    "ssh"
)


# ssh → Check whether additional investigation is needed

builder.add_edge(
    "ssh",
    "check_more"
)


# ============================================================
# Additional investigation？
# ============================================================

builder.add_conditional_edges(
    "check_more",
    lambda state:
        "ssh" if state["need_more"]
        else "answer",
    {
        "ssh": "ssh",
        "answer": "answer"
    }
)


# answer → END

builder.add_edge(
    "answer",
    END
)


graph = builder.compile()


# ============================================================
# Run the agent
# ============================================================

if __name__ == "__main__":

    user_message = input(
        "Enter your inquiry > "
    )

    result = graph.invoke(
        {
            "user_message": user_message
        }
    )

    print("\n==============================")
    print("Final Response")
    print("==============================")

    print(
        result["answer"]
    )