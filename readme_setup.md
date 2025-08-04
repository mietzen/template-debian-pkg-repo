# Debian Repository on GitHub Pages

This repository automatically creates and maintains a Debian package repository hosted on GitHub Pages by pulling `.deb` packages from GitHub releases.

## Setup

### Configure Packages

Edit `packages.yml` to list the GitHub repositories you want to include:

```yaml
packages:
  example-package-1:
    url: https://github.com/user/repo1
    version: "1.2.3"
    asset_regex: '.*amd64.*'
  example-package-2:
    url: https://github.com/user/repo2
    version: "2.0.1"
    asset_regex: '.*all.*'
```

### Enable GitHub Pages

1. Go to your repository settings
2. Navigate to "Pages" in the sidebar
3. Select "GitHub Actions" as the source
4. The workflows will automatically deploy your repository

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
       asset_regex: '.*amd64.*'
   ```

2. The update workflow will automatically detect new releases daily, or you can trigger it manually:
   - Go to Actions → Update Package List → Run workflow

## License

This repository structure and scripts are provided under MIT License. Individual packages retain their original licenses.
