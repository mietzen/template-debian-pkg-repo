#!/usr/bin/env python3

import os
import re
import yaml
import requests
import sys

def get_latest_release_with_filter(repo_url: str, github_token: str, asset_regex: str | None) -> str | None:
    """Get the latest release tag that contains at least one .deb asset (and matches asset_regex if provided)."""
    # Extract owner/repo from URL
    if repo_url.startswith('https://github.com/'):
        repo_path = repo_url.replace('https://github.com/', '')
    else:
        raise ValueError(f"Invalid GitHub URL: {repo_url}")

    headers = {
        'Authorization': f'token {github_token}',
        'Accept': 'application/vnd.github.v3+json'
    }

    # Query releases list instead of only 'latest' to allow regex filtering fallback
    api_url = f"https://api.github.com/repos/{repo_path}/releases"
    response = requests.get(api_url, headers=headers)
    if response.status_code != 200:
        print(f"Failed to get releases for {repo_url}: {response.status_code}")
        return None

    releases = response.json()
    if not isinstance(releases, list) or not releases:
        print(f"No releases found for {repo_url}")
        return None

    # Precompile regex if provided
    pattern = None
    if asset_regex:
        try:
            pattern = re.compile(asset_regex)
        except re.error as e:
            print(f"Invalid asset_regex '{asset_regex}' for {repo_url}: {e}. Ignoring regex for update check.")
            pattern = None

    for rel in releases:
        assets = rel.get('assets', []) or []
        # Filter .deb assets
        deb_assets = [a for a in assets if a.get('name', '').endswith('.deb')]
        if not deb_assets:
            continue
        if pattern:
            deb_assets = [a for a in deb_assets if pattern.search(a.get('name', ''))]
            if not deb_assets:
                continue
        # Found a suitable release
        return rel.get('tag_name')

    # No release satisfies the filter
    return None

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
        asset_regex = package_info.get('asset_regex')

        if not repo_url:
            print(f"No URL specified for package {package_name}")
            continue

        print(f"Checking {package_name} at {repo_url} (asset_regex={asset_regex if asset_regex else 'none'})")

        try:
            latest_version = get_latest_release_with_filter(repo_url, github_token, asset_regex)
            if latest_version and latest_version != current_version:
                print(f"Updating {package_name}: {current_version} -> {latest_version}")
                packages[package_name]['version'] = latest_version
                updated = True
            elif latest_version:
                print(f"{package_name} is up to date at {latest_version}")
            else:
                print(f"No suitable release found for {package_name} considering asset filter")
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
