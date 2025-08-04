#!/usr/bin/env python3

import os
import re
import yaml
import requests
import hashlib
import tarfile
import io
from typing import Dict, List, Tuple
import tempfile
import subprocess
from collections import defaultdict

def extract_deb_control(deb_data: bytes) -> Dict[str, str]:
    """Extract control information from a .deb package in memory."""

    # .deb files are ar archives containing control.tar.* and data.tar.*
    # We need to extract the control.tar.* and read the control file

    with tempfile.NamedTemporaryFile() as temp_deb:
        temp_deb.write(deb_data)
        temp_deb.flush()

        # Try control.tar.xz first, then control.tar.gz as fallback
        control_tar_data = None
        for member in ('control.tar.xz', 'control.tar.gz'):
            try:
                result = subprocess.run(
                    ['ar', 'p', temp_deb.name, member],
                    capture_output=True,
                    check=True
                )
                control_tar_data = result.stdout
                mode = 'r:xz' if member.endswith('.xz') else 'r:gz'
                break
            except subprocess.CalledProcessError:
                continue

        if control_tar_data is None:
            raise ValueError("No control.tar.* found in package")

    # Extract control file from control tar
    with tarfile.open(fileobj=io.BytesIO(control_tar_data), mode=mode) as tar:
        control_file = tar.extractfile('control')
        if control_file is None:
            raise ValueError("No control file found in package")

        control_content = control_file.read().decode('utf-8', errors='replace')

    # Parse control file
    control_info: Dict[str, str] = {}
    current_field = None

    for line in control_content.split('\n'):
        line = line.rstrip()
        if not line:
            continue

        if line.startswith(' ') or line.startswith('\t'):
            # Continuation of previous field
            if current_field:
                control_info[current_field] += '\n' + line
        else:
            # New field
            if ':' in line:
                field, value = line.split(':', 1)
                field = field.strip()
                value = value.strip()
                control_info[field] = value
                current_field = field

    return control_info

def _match_asset(name: str, regex: str | None) -> bool:
    if not name.endswith('.deb'):
        return False
    if not regex:
        return True
    try:
        return re.search(regex, name) is not None
    except re.error as e:
        print(f"Invalid asset_regex '{regex}': {e}. Skipping regex filtering for this package.")
        return True

def _save_deb(pool_dir: str, filename: str, data: bytes) -> str:
    os.makedirs(pool_dir, exist_ok=True)
    path = os.path.join(pool_dir, filename)
    with open(path, 'wb') as f:
        f.write(data)
    return path

def download_deb_packages(packages_config: Dict) -> Tuple[Dict[str, List[Dict]], List[Dict]]:
    """Download .deb packages and extract their metadata.
    Returns a tuple: (packages_by_arch, packages_all)
    """

    github_token = os.environ.get('GITHUB_TOKEN')
    headers = {
        'Authorization': f'token {github_token}',
        'Accept': 'application/vnd.github.v3+json'
    } if github_token else {}

    packages_by_arch: Dict[str, List[Dict]] = defaultdict(list)
    packages_all: List[Dict] = []

    for package_name, package_info in packages_config.get('packages', {}).items():
        repo_url = package_info.get('url')
        version = package_info.get('version')
        asset_regex = package_info.get('asset_regex')

        if not repo_url or not version:
            print(f"Skipping {package_name}: missing url or version")
            continue

        # Extract owner/repo from URL
        repo_path = repo_url.replace('https://github.com/', '')

        # Determine tag
        tag_candidates = [version if version.startswith('v') else f"v{version}", version]
        response = None
        for tag in tag_candidates:
            api_url = f"https://api.github.com/repos/{repo_path}/releases/tags/{tag}"
            print(f"Fetching release info for {package_name} {tag}")
            response = requests.get(api_url, headers=headers)
            if response.status_code == 200:
                break
        if not response or response.status_code != 200:
            print(f"Failed to get release {version} for {repo_path}: {response.status_code if response else 'no response'}")
            continue

        release_data = response.json()
        assets = release_data.get('assets', [])

        # Filter assets by .deb and asset_regex if provided
        filtered_assets = [a for a in assets if _match_asset(a.get('name', ''), asset_regex)]

        if asset_regex and not filtered_assets:
            print(f"No assets matched asset_regex '{asset_regex}' for package {package_name} in release {release_data.get('tag_name')}. Skipping.")
            continue

        for asset in filtered_assets:
            asset_name = asset.get('name', '')
            url = asset.get('browser_download_url')
            if not url:
                print(f"Asset {asset_name} has no download URL. Skipping.")
                continue

            print(f"Downloading {asset_name}")
            deb_response = requests.get(url)
            if deb_response.status_code != 200:
                print(f"Failed to download {asset_name}")
                continue

            try:
                # Extract control information
                control_info = extract_deb_control(deb_response.content)

                # Determine architecture from control (truth source)
                arch = control_info.get('Architecture', 'all').strip()

                # Calculate file hashes (only SHA256 for modern repositories)
                sha256_hash = hashlib.sha256(deb_response.content).hexdigest()

                # Save package file
                pkg_name = control_info['Package']
                pool_dir = f"pages/pool/main/{pkg_name[0]}/{pkg_name}"
                package_filename = asset_name
                _save_deb(pool_dir, package_filename, deb_response.content)

                # Build base package entry (Architecture field will be set below)
                base_entry = {
                    'Package': pkg_name,
                    'Version': control_info['Version'],
                    'Maintainer': control_info.get('Maintainer', 'Unknown'),
                    'Description': control_info.get('Description', ''),
                    'Section': control_info.get('Section', 'misc'),
                    'Priority': control_info.get('Priority', 'optional'),
                    'Filename': f"pool/main/{pkg_name[0]}/{pkg_name}/{package_filename}",
                    'Size': str(len(deb_response.content)),
                    'SHA256': sha256_hash,
                }
                # Add optional fields if present
                for field in ['Depends', 'Recommends', 'Suggests', 'Conflicts', 'Provides', 'Replaces']:
                    if field in control_info:
                        base_entry[field] = control_info[field]

                if arch == 'all':
                    # Keep a single canonical entry with Architecture: all
                    entry = dict(base_entry)
                    entry['Architecture'] = 'all'
                    packages_all.append(entry)
                    print(f"Added {pkg_name} {control_info['Version']} to Architecture: all")
                else:
                    # Record into the discovered arch bucket
                    entry = dict(base_entry)
                    entry['Architecture'] = arch
                    packages_by_arch[arch].append(entry)
                    print(f"Added {pkg_name} {control_info['Version']} to {arch}")

            except Exception as e:
                print(f"Error processing {asset_name}: {e}")
                continue

    return packages_by_arch, packages_all

def _emit_packages_file(packages_dir: str, packages: List[Dict]) -> None:
    os.makedirs(packages_dir, exist_ok=True)
    packages_content: List[str] = []

    for package in packages:
        package_lines: List[str] = []
        # Required fields in specific order
        required_fields = ['Package', 'Version', 'Architecture', 'Maintainer',
                           'Filename', 'Size', 'SHA256']
        for field in required_fields:
            if field in package:
                package_lines.append(f"{field}: {package[field]}")

        # Optional fields
        optional_fields = ['Section', 'Priority', 'Depends', 'Recommends',
                           'Suggests', 'Conflicts', 'Provides', 'Replaces', 'Description']
        for field in optional_fields:
            if field in package:
                if field == 'Description':
                    desc_lines = str(package[field]).split('\n')
                    package_lines.append(f"Description: {desc_lines[0]}")
                    for desc_line in desc_lines[1:]:
                        package_lines.append(f" {desc_line}")
                else:
                    package_lines.append(f"{field}: {package[field]}")
        packages_content.append('\n'.join(package_lines))

    content = '\n\n'.join(packages_content) + ('\n' if packages_content else '')
    packages_path = os.path.join(packages_dir, 'Packages')
    with open(packages_path, 'w') as f:
        f.write(content)
    # Gzip
    import gzip
    with open(packages_path, 'rb') as fin, gzip.open(os.path.join(packages_dir, 'Packages.gz'), 'wb') as fout:
        fout.writelines(fin)

def generate_packages_files(packages_by_arch: Dict[str, List[Dict]], packages_all: List[Dict]) -> List[str]:
    """Generate Packages files for each architecture and return list of architectures with packages."""
    active_architectures: List[str] = []

    # Always emit binary-all (with only Architecture: all packages)
    all_dir = "pages/dists/stable/main/binary-all"
    _emit_packages_file(all_dir, packages_all)
    if packages_all:
        active_architectures.append('all')

    # Emit per-arch, including duplication of 'all' packages per approval
    for arch, packages in packages_by_arch.items():
        combined = list(packages)
        # Duplicate all packages into each arch's Packages list
        combined.extend(packages_all)
        if not combined and arch not in active_architectures:
            # Nothing to write for this arch
            continue
        packages_dir = f"pages/dists/stable/main/binary-{arch}"
        _emit_packages_file(packages_dir, combined)
        active_architectures.append(arch)

    return active_architectures

def main():
    """Main function to build the repository."""

    # Create base directory structure
    os.makedirs("pages/pool/main", exist_ok=True)
    os.makedirs("pages/dists/stable/main", exist_ok=True)

    # Load packages configuration
    with open('packages.yml', 'r') as f:
        packages_config = yaml.safe_load(f)

    # Download packages and extract metadata
    packages_by_arch, packages_all = download_deb_packages(packages_config)

    # Generate Packages files and get active architectures
    active_architectures = generate_packages_files(packages_by_arch, packages_all)

    # No longer write active_architectures.txt; derive dynamically in workflow
    print(f"Repository build completed with architectures: {', '.join(active_architectures)}")

if __name__ == '__main__':
    main()
