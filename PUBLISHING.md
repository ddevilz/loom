# Loom MCP Server - Publication Guide

This guide walks you through publishing Loom to PyPI and the Smithery MCP registry so anyone can use it.

## ✅ Pre-Publication Checklist

All items below are **COMPLETE** and ready for publication:

- [x] **PyPI metadata** - Added keywords, classifiers, project URLs
- [x] **Package structure** - Proper `pyproject.toml` configuration
- [x] **Documentation** - Comprehensive README, MCP docs, architecture guides
- [x] **License** - MIT License included
- [x] **Contributing guidelines** - CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md
- [x] **Tests** - 9 MCP server tests passing, full test suite available
- [x] **CI/CD** - GitHub Actions workflow configured
- [x] **Version** - Updated to 0.1.1
- [x] **CHANGELOG** - Updated with release notes
- [x] **MCP registry config** - smithery.json created
- [x] **Build verification** - Package builds successfully

## 📦 Step 1: Publish to PyPI

### Prerequisites

1. **PyPI account**: Create at https://pypi.org/account/register/
2. **API token**: Generate at https://pypi.org/manage/account/token/
3. **Build tools**: Already installed with `uv`

### Build the Package

The package has already been built successfully:

```bash
uv build
```

This creates:
- `dist/loom-0.1.1.tar.gz` (source distribution)
- `dist/loom-0.1.1-py3-none-any.whl` (wheel)

### Test the Package Locally (Optional)

```bash
# Install in a clean environment
uv pip install dist/loom-0.1.1-py3-none-any.whl

# Verify it works
loom --dev
```

### Upload to TestPyPI (Recommended First Step)

Test the upload process on TestPyPI first:

```bash
# Install twine if not already available
uv pip install twine

# Upload to TestPyPI
uv run twine upload --repository testpypi dist/*
```

You'll be prompted for:
- Username: `__token__`
- Password: Your TestPyPI API token (starts with `pypi-`)

Test installation from TestPyPI:

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ loom
```

### Upload to PyPI (Production)

Once TestPyPI works, upload to production PyPI:

```bash
uv run twine upload dist/*
```

You'll be prompted for:
- Username: `__token__`
- Password: Your PyPI API token (starts with `pypi-`)

### Verify Publication

After upload, verify at:
- Package page: https://pypi.org/project/loom/
- Installation: `pip install loom`

## 🌐 Step 2: Submit to Smithery MCP Registry

Smithery is the official MCP server registry that makes your server discoverable to MCP clients.

### Prerequisites

1. **GitHub account** - Your repository is already public
2. **Smithery account** - Sign up at https://smithery.ai

### Submission Process

1. **Go to Smithery**: Visit https://smithery.ai/submit

2. **Submit your server**:
   - Repository URL: `https://github.com/ddevilz/loom`
   - The `smithery.json` file is already configured in your repo root
   - Smithery will automatically detect and validate it

3. **Smithery will validate**:
   - Repository structure
   - `smithery.json` configuration
   - Package availability on PyPI
   - Documentation quality

4. **Review and approve**: Smithery team will review (usually 1-3 days)

### Alternative: Manual Registry Entry

If Smithery submission isn't available, you can also:

1. **Add to MCP servers list**: Submit a PR to https://github.com/modelcontextprotocol/servers
2. **Create documentation**: Add your server to community lists and forums

## 📢 Step 3: Announce and Promote

### GitHub Release

Create a GitHub release for v0.1.1:

```bash
git tag v0.1.1
git push origin v0.1.1
```

Then create a release at: https://github.com/ddevilz/loom/releases/new

Use this template:

```markdown
# Loom v0.1.1 - MCP Server for Code Intelligence

Loom is now available on PyPI! 🎉

## Installation

```bash
pip install loom
```

## What's New in 0.1.1

- PyPI publication with full metadata
- Comprehensive MCP documentation
- Smithery registry configuration
- Enhanced installation and setup guides

## Quick Start

1. Install: `pip install loom`
2. Start FalkorDB: `docker run -d -p 6379:6379 falkordb/falkordb`
3. Index your repo: `loom analyze . --graph-name myproject`
4. Configure MCP client (see [docs/MCP.md](docs/MCP.md))

## Features

- 🔍 Semantic code search
- 📊 Call graph analysis
- 📝 Documentation linking
- 🔄 Drift detection
- 🎯 Impact analysis
- 🎫 Jira integration
- 🤖 MCP server for AI agents

See [CHANGELOG.md](CHANGELOG.md) for full details.
```

### Update Repository

Update your README badges (optional):

```markdown
[![PyPI version](https://badge.fury.io/py/loom.svg)](https://badge.fury.io/py/loom)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
```

### Community Outreach

Share your MCP server:

1. **MCP Discord**: Announce in the Model Context Protocol Discord
2. **Reddit**: Post in r/MachineLearning, r/Python
3. **Twitter/X**: Share with #MCP #CodeIntelligence hashtags
4. **Dev.to**: Write a tutorial article
5. **Hacker News**: Submit to Show HN

## 🔄 Future Updates

When you release new versions:

1. **Update version** in `pyproject.toml` and `smithery.json`
2. **Update CHANGELOG.md** with new features/fixes
3. **Build**: `uv build`
4. **Upload**: `uv run twine upload dist/*`
5. **Tag release**: `git tag vX.Y.Z && git push --tags`
6. **Create GitHub release** with changelog
7. **Smithery auto-updates** from your repository

## 📊 Monitor Usage

After publication, monitor:

- **PyPI stats**: https://pypistats.org/packages/loom
- **GitHub stars/forks**: Track repository growth
- **Issues**: Respond to user feedback
- **Downloads**: Monitor adoption trends

## 🆘 Troubleshooting

### PyPI Upload Fails

**Error: File already exists**
- You cannot re-upload the same version
- Increment version in `pyproject.toml`
- Rebuild and upload again

**Error: Invalid credentials**
- Ensure you're using `__token__` as username
- Verify your API token is correct
- Check token hasn't expired

### Smithery Validation Fails

**Error: Invalid smithery.json**
- Validate JSON syntax
- Check all required fields are present
- Ensure version matches PyPI

**Error: Package not found**
- Wait a few minutes after PyPI upload
- Verify package name matches exactly

## 📝 Maintenance Checklist

Regular maintenance tasks:

- [ ] **Weekly**: Check GitHub issues and PRs
- [ ] **Monthly**: Update dependencies (`uv sync --upgrade`)
- [ ] **Quarterly**: Review and update documentation
- [ ] **Per release**: Update CHANGELOG, version, and publish

## 🎯 Success Metrics

Track these metrics to measure success:

- PyPI downloads per month
- GitHub stars and forks
- Active issues and PRs
- Community contributions
- MCP client integrations

## 📚 Resources

- **PyPI Publishing Guide**: https://packaging.python.org/tutorials/packaging-projects/
- **Smithery Documentation**: https://smithery.ai/docs
- **MCP Specification**: https://modelcontextprotocol.io
- **Semantic Versioning**: https://semver.org

---

## Ready to Publish? 🚀

Your Loom MCP server is **100% ready for publication**. Follow the steps above to:

1. ✅ Publish to PyPI (15 minutes)
2. ✅ Submit to Smithery (5 minutes)
3. ✅ Create GitHub release (5 minutes)
4. ✅ Announce to community (30 minutes)

**Total time to go live: ~1 hour**

Good luck with your launch! 🎉
