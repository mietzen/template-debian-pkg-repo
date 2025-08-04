#!/usr/bin/env python3

import os
import yaml
import requests
import sys

def get_latest_release(repo_url: str, github_token: str) -> str:
    """Get the latest release tag from a GitHub repository."""
    # Extract owner/repo from URL
    if repo_url.startswith('https://github.com/'):
        repo_path = repo_url.replace('https://github.com/', '')
    else:
        raise ValueError(f"Invalid GitHub URL: {repo_url}")

    api_url = f"https://api.github.com/repos/{repo_path}/releases/latest"
    headers = {
        'Authorization': f'token {github_token}',
        'Accept': 'application/vnd.github.v3+json'
    }

    response = requests.get(api_url, headers=headers)
    if response.status_code == 404:
        print(f"No releases found for {repo_url}")
        return None
    elif response.status_code != 200:
        print(f"Failed to get releases for {repo_url}: {response.status_code}")
        return None

    release_data = response.json()

    # Check if any .deb files are attached
    has_deb_files = any(
        asset['name'].endswith('.deb')
        for asset in release_data.get('assets', [])
    )

    if not has_deb_files:
        print(f"No .deb files found in latest release for {repo_url}")
        return None

    return release_data['tag_name']

def update_packages_file():
    """Update the packages.yml file with latest versions."""
    github_token = os.environ.get('GITHUB_TOKEN')
    if not github_token:
        print("GITHUB_TOKEN environment variable not set")
        sys.exit(1)

    # Load current packages configuration
    try:
        with open('packages.yml', 'r') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print("packages.yml not found")
        sys.exit(1)

    packages = config.get('packages', {})
    updated = False

    for package_name, package_info in packages.items():
        repo_url = package_info.get('url')
        current_version = package_info.get('version')

        if not repo_url:
            print(f"No URL specified for package {package_name}")
            continue

        print(f"Checking {package_name} at {repo_url}")

        try:
            latest_version = get_latest_release(repo_url, github_token)
            if latest_version and latest_version != current_version:
                print(f"Updating {package_name}: {current_version} -> {latest_version}")
                packages[package_name]['version'] = latest_version
                updated = True
            elif latest_version:
                print(f"{package_name} is up to date at {latest_version}")
            else:
                print(f"Could not determine latest version for {package_name}")
        except Exception as e:
            print(f"Error checking {package_name}: {e}")

    if updated:
        # Write updated configuration back to file
        with open('packages.yml', 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=True)
        print("packages.yml updated")
    else:
        print("No updates needed")

if __name__ == '__main__':
    update_packages_file()
