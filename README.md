# AI Agent for Network Operations

An AI-powered network operations assistant that uses Zabbix monitoring data and SSH-based Cisco device diagnostics to support network troubleshooting.

## Overview

This project aims to automate and streamline network troubleshooting by combining AI agents, network monitoring, and Cisco device diagnostics.

The agent retrieves network problem information from Zabbix, analyzes the reported issues, and executes relevant diagnostic commands on Cisco devices via SSH. It generates a natural-language summary of the findings and potential causes, with the response language depending on the user's inquiry.

## Features

- **Zabbix Integration**: Retrieves network problem information through the Zabbix API.
- **AI-Powered Analysis**: Uses an LLM to analyze monitoring data and support troubleshooting decisions.
- **SSH-Based Diagnostics**: Connects to Cisco devices using Netmiko to execute relevant diagnostic commands.
- **Targeted Investigation**: Uses monitoring information to identify relevant devices for further investigation.
- **Natural-Language Reporting**: Summarizes diagnostic findings and potential causes in a human-readable format.
- **Investigation Workflow**: Uses LangGraph to manage the agent's workflow and conditional transitions between processing steps.

## Architecture

The agent follows this workflow:

1. Receive a network-related inquiry.
2. Retrieve network problem information from Zabbix.
3. Identify the relevant Cisco devices based on the monitoring data.
4. Connect to the relevant devices via SSH.
5. Execute diagnostic commands and collect device information.
6. Determine whether further investigation is required.
7. Generate a natural-language report summarizing the findings and potential causes.

## Technology Stack

- Python
- LangGraph
- Google Gemini
- Zabbix API
- Netmiko
- Cisco IOS

## Configuration

Before running the agent, configure the following settings for your environment.

Zabbix API URL: Set the URL of your Zabbix API endpoint.

Zabbix credentials: Configure the username and password used to access the Zabbix API.

Google Gemini API key: Set your Google API key.

Cisco device SSH credentials: Configure the SSH username and password required to access Cisco devices. Target device IP addresses are obtained from Zabbix monitoring data.

Use environment variables for credentials and other sensitive information wherever possible.

Some settings may need to be adjusted in the source code to match your environment.

Important: Do not commit API keys, passwords, or other sensitive information to the repository.

## Project Status

**Version 1 — Initial implementation**

This project is under active development. The initial version focuses on integrating network monitoring data, AI-driven analysis, and SSH-based Cisco device diagnostics.

Future enhancements may include improved investigation strategies, conversation history, persistent memory, and broader network device support.

## Disclaimer

This project is intended for learning, experimentation, and demonstration purposes. Always validate AI-generated diagnostic findings before applying changes to production network environments.
