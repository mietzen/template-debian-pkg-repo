# Debian Repository on GitHub Pages

This template repository automatically creates and maintains a Debian package repository hosted on GitHub Pages by pulling `.deb` packages from GitHub releases.

## Setup

### Configure Packages

Edit `packages.yml` to list the GitHub repositories you want to include:

```yaml
packages:
  example-package-1:
    url: https://github.com/user/repo1
    version: "1.2.3"
    # Optional regex to select which .deb assets to include from the release
    asset_regex: '.*amd64.*'
  example-package-2:
    url: https://github.com/user/repo2
    version: "2.0.1"
    asset_regex: '.*all.*'
```

#### asset_regex usage

- asset_regex is an optional regular expression used to filter release assets by filename before downloading. Only files ending with .deb are ever considered. If asset_regex is omitted, all .deb assets from the release are eligible.
- Invalid regular expressions are safely ignored and treated as if no filter was provided.
- Examples:
  - Match architecture-specific packages:
    - '.*amd64.*' selects .deb assets that contain amd64 in their filename.
  - Match no-arch packages:
    - '.*all.*' selects Architecture: all packages that are commonly built once for all architectures.
  - Match multiple patterns:
    - '.*(amd64|arm64).*' selects both amd64 and arm64 assets from the same release.
  - Capture groups are allowed but unused; matching is boolean only.

Note: Filtering by asset_regex affects which assets are downloaded, but the actual Architecture used in repository metadata is always derived from the package’s control file inside the .deb.

### Enable GitHub Pages

1. Go to your repository settings
2. Navigate to "Pages" in the sidebar
3. Select "GitHub Actions" as the source
4. The workflows will automatically deploy your repository

## How architectures are determined (dynamic discovery)

Architectures are discovered dynamically based on the Packages files that are generated:

- The build step downloads selected .deb assets and reads their control metadata.
- Packages are grouped by their control Architecture field:
  - If Architecture is all, entries are added to a dedicated all bucket.
  - Otherwise, entries are associated with their specific architecture (e.g., amd64, arm64, i386, etc.).
- Packages files are generated per-architecture and for all. Each per-arch Packages file includes the union of:
  - All packages whose Architecture equals that arch
  - All packages whose Architecture is all
- The Release file Architectures field is derived at deploy time by scanning which binary- directories exist under dists/stable/main.

Result:
- If only Architecture: all packages exist, the repository will publish binary-all and the Release file will list Architectures: all.
- If you also include, for example, amd64 packages, both binary-all and binary-amd64 are present and Release will list Architectures: all amd64.

## Special handling: Architecture: all

- A single canonical Packages file for all is generated at dists/stable/main/binary-all/Packages.
- Each per-architecture Packages file additionally includes the all entries. This ensures clients on any specific architecture can install no-arch packages without mixing components.

Practical implications:
- You can publish only no-arch packages and still have a valid repository (Architectures: all).
- Mixing all with arch-specific packages is supported; clients will see all packages regardless of the chosen architecture.

## Usage

### Adding your Repository to your System

```bash
echo "deb [trusted=yes] https://<GH-USER>.github.io/<REPO-NAME>/ stable main" | sudo tee /etc/apt/sources.list.d/my-deb-pkgs.list
sudo apt-get update
```

### Adding New Packages

1. Add the package to `packages.yml`:
   ```yaml
   packages:
     new-package:
       url: https://github.com/owner/new-package-repo
       version: "1.0.0"
       # Optional: filter assets by filename to specific architectures
       asset_regex: '.*(amd64|arm64|all).*'
   ```

2. The update workflow will automatically detect new releases daily, or you can trigger it manually:
   - Go to Actions → Update Package List → Run workflow

## End-to-end test (ubuntu-latest)

You can validate dynamic architecture discovery, Release Architectures, and Packages contents using a sample packages.yml that references assets across multiple architectures. On ubuntu-latest, the deploy workflow:

- Installs dpkg-dev and Python tooling
- Builds pages/pool and dists/stable/main/binary-* with Packages and Packages.gz
- Derives the Architectures list by scanning existing binary-* directories and writes it into dists/stable/Release
- Adds SHA256 checksums for Packages and Packages.gz

To run locally in GitHub Actions:
- Push a packages.yml that selects multi-arch assets (e.g., an amd64 .deb, an arm64 .deb, and an all .deb using asset_regex).
- Run the “Deploy Debian Repository” workflow; verify in artifacts:
  - dists/stable/Release contains Architectures: all amd64 arm64 (order may vary)
  - dists/stable/main/binary-all/Packages has only Architecture: all entries
  - dists/stable/main/binary-amd64/Packages includes amd64 entries plus the all entries
  - dists/stable/main/binary-arm64/Packages includes arm64 entries plus the all entries

## License

This repository structure and scripts are provided under MIT License. Individual packages retain their original licenses.
