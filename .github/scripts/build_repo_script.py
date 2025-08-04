#!/usr/bin/env python3

import os
import yaml
import requests
import hashlib
import tarfile
import io
from typing import Dict, List
import tempfile
import subprocess

def extract_deb_control(deb_data: bytes) -> Dict[str, str]:
    """Extract control information from a .deb package in memory."""

    # .deb files are ar archives containing control.tar.xz and data.tar.xz
    # We need to extract the control.tar.xz and read the control file

    with tempfile.NamedTemporaryFile() as temp_deb:
        temp_deb.write(deb_data)
        temp_deb.flush()

        # Use ar to extract control.tar.xz
        result = subprocess.run(
            ['ar', 'p', temp_deb.name, 'control.tar.xz'],
            capture_output=True,
            check=True
        )
        control_tar_data = result.stdout

    # Extract control file from control.tar.xz
    with tarfile.open(fileobj=io.BytesIO(control_tar_data), mode='r:xz') as tar:
        control_file = tar.extractfile('control')
        if control_file is None:
            raise ValueError("No control file found in package")

        control_content = control_file.read().decode('utf-8')

    # Parse control file
    control_info = {}
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

def download_deb_packages(packages_config: Dict) -> Dict[str, List[Dict]]:
    """Download .deb packages and extract their metadata."""

    github_token = os.environ.get('GITHUB_TOKEN')
    headers = {
        'Authorization': f'token {github_token}',
        'Accept': 'application/vnd.github.v3+json'
    } if github_token else {}

    packages_by_arch = {'amd64': [], 'arm64': [], 'armhf': []}

    for package_name, package_info in packages_config.get('packages', {}).items():
        repo_url = package_info['url']
        version = package_info['version']

        # Extract owner/repo from URL
        repo_path = repo_url.replace('https://github.com/', '')

        # Get release information
        if version.startswith('v'):
            tag = version
        else:
            tag = f"v{version}"

        api_url = f"https://api.github.com/repos/{repo_path}/releases/tags/{tag}"

        print(f"Fetching release info for {package_name} {version}")
        response = requests.get(api_url, headers=headers)

        if response.status_code == 404:
            # Try without 'v' prefix
            tag = version
            api_url = f"https://api.github.com/repos/{repo_path}/releases/tags/{tag}"
            response = requests.get(api_url, headers=headers)

        if response.status_code != 200:
            print(f"Failed to get release {version} for {repo_path}: {response.status_code}")
            continue

        release_data = response.json()

        # Download .deb files
        for asset in release_data['assets']:
            if not asset['name'].endswith('.deb'):
                continue

            print(f"Downloading {asset['name']}")
            deb_response = requests.get(asset['browser_download_url'])

            if deb_response.status_code != 200:
                print(f"Failed to download {asset['name']}")
                continue

            try:
                # Extract control information
                control_info = extract_deb_control(deb_response.content)

                # Determine architecture
                arch = control_info.get('Architecture', 'all')
                if arch == 'all':
                    # Add to all architectures
                    target_archs = ['amd64', 'arm64', 'armhf']
                elif arch in packages_by_arch:
                    target_archs = [arch]
                else:
                    print(f"Unsupported architecture {arch} for {asset['name']}")
                    continue

                # Calculate file hashes (only SHA256 for modern repositories)
                sha256_hash = hashlib.sha256(deb_response.content).hexdigest()

                # Save package file
                pool_dir = f"pages/pool/main/{control_info['Package'][0]}/{control_info['Package']}"
                os.makedirs(pool_dir, exist_ok=True)

                package_filename = asset['name']
                package_path = os.path.join(pool_dir, package_filename)

                with open(package_path, 'wb') as f:
                    f.write(deb_response.content)

                # Create package entry for each target architecture
                for target_arch in target_archs:
                    package_entry = {
                        'Package': control_info['Package'],
                        'Version': control_info['Version'],
                        'Architecture': target_arch if arch != 'all' else 'all',
                        'Maintainer': control_info.get('Maintainer', 'Unknown'),
                        'Description': control_info.get('Description', ''),
                        'Section': control_info.get('Section', 'misc'),
                        'Priority': control_info.get('Priority', 'optional'),
                        'Filename': f"pool/main/{control_info['Package'][0]}/{control_info['Package']}/{package_filename}",
                        'Size': str(len(deb_response.content)),
                        'SHA256': sha256_hash,
                    }

                    # Add optional fields if present
                    for field in ['Depends', 'Recommends', 'Suggests', 'Conflicts', 'Provides', 'Replaces']:
                        if field in control_info:
                            package_entry[field] = control_info[field]

                    packages_by_arch[target_arch].append(package_entry)
                    print(f"Added {control_info['Package']} {control_info['Version']} to {target_arch}")

            except Exception as e:
                print(f"Error processing {asset['name']}: {e}")
                continue

    return packages_by_arch

def generate_packages_files(packages_by_arch: Dict[str, List[Dict]]) -> List[str]:
    """Generate Packages files for each architecture and return list of architectures with packages."""

    active_architectures = []

    for arch, packages in packages_by_arch.items():
        if not packages:
            continue

        packages_dir = f"pages/dists/stable/main/binary-{arch}"
        os.makedirs(packages_dir, exist_ok=True)
        active_architectures.append(arch)

        packages_content = []

        for package in packages:
            package_lines = []

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
                        # Description can be multi-line
                        desc_lines = package[field].split('\n')
                        package_lines.append(f"Description: {desc_lines[0]}")
                        for desc_line in desc_lines[1:]:
                            package_lines.append(f" {desc_line}")
                    else:
                        package_lines.append(f"{field}: {package[field]}")

            packages_content.append('\n'.join(package_lines))

        # Write Packages file
        packages_file_content = '\n\n'.join(packages_content) + '\n'

        with open(f"{packages_dir}/packages_list.txt", 'w') as f:
            f.write(packages_file_content)

        print(f"Generated Packages file for {arch} with {len(packages)} packages")

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
    packages_by_arch = download_deb_packages(packages_config)

    # Generate Packages files and get active architectures
    active_architectures = generate_packages_files(packages_by_arch)

    # Write active architectures to a file for the workflow to use
    with open('pages/active_architectures.txt', 'w') as f:
        f.write(' '.join(active_architectures))

    print(f"Repository build completed with architectures: {', '.join(active_architectures)}")

if __name__ == '__main__':
    main()
