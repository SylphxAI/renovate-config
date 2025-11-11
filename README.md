<div align="center">

# Renovate Config 🔄

**Unified Renovate configuration for multi-stack projects**

[![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](https://github.com/SylphxAI/renovate-config/blob/main/LICENSE)
[![Renovate](https://img.shields.io/badge/Renovate-enabled-blue?style=flat-square&logo=renovatebot)](https://renovatebot.com)

**14 tech stacks** • **Auto-detection** • **Smart grouping** • **Weekend updates**

[Quick Start](#-quick-start) • [Features](#-key-features) • [Stack Support](#-supported-stacks)

</div>

---

## 🚀 Overview

A unified Renovate configuration that automatically handles dependency updates across multiple technology stacks with smart defaults and minimal configuration.

**The Problem:**
```
Managing Renovate across projects:
- Duplicate config in every repo ❌
- Inconsistent update strategies ❌
- Manual stack-specific rules ❌
- Update noise during weekdays ❌
```

**The Solution:**
```
Shared Renovate Config:
- Single source of truth ✅
- Auto stack detection ✅
- Smart defaults for 14 stacks ✅
- Weekend-only updates ✅
```

**Result: Consistent, automated dependency management across all your projects.**

---

## 🚀 Quick Start

Create `.github/renovate.json` (or `renovate.json`) in your project:

```json
{
  "extends": ["github>SylphxAI/renovate-config"]
}
```

That's it! Renovate will automatically:
- ✅ Detect your project type
- ✅ Apply appropriate update rules
- ✅ Schedule updates for weekends
- ✅ Auto-merge minor/patch updates

---

## ✨ Key Features

### Automation & Intelligence

| Feature | Description | Benefit |
|---------|-------------|---------|
| **Auto-detection** | Identifies project stack automatically | Zero manual config |
| **Smart grouping** | Groups related dependencies | Fewer PRs, easier reviews |
| **Auto-merge** | Minor/patch updates merge automatically | Save review time |
| **Weekend schedule** | Updates run on weekends only | No weekday disruptions |
| **Dependency dashboard** | Centralized update overview | Easy monitoring |
| **Rate limiting** | Max 2 PRs/hour, 5 concurrent | Avoid overwhelming CI |

### Update Strategy

- **Minor/Patch**: Auto-merge (safe updates)
- **Major**: Labeled as "breaking", requires review
- **Security**: Immediate, high priority
- **Labels**: Auto-tagged by update type

---

## 🛠️ Supported Stacks

### Backend & Containerization

| Technology | Package Manager | Features |
|------------|-----------------|----------|
| **Docker** | Docker Hub, etc. | Digest pinning, auto-merge minor |
| **PHP** | Composer | Laravel/Symfony grouping |
| **Python** | pip, pipenv, poetry | Django/Flask/testing groups |

### Mobile Development

| Technology | Package Manager | Features |
|------------|-----------------|----------|
| **Android** | Gradle | androidx/Google grouping |
| **iOS** | CocoaPods, Swift | Proper iOS dependency groups |
| **Flutter/Dart** | pub | Ignores platform-specific dirs |

### Frontend & JavaScript

| Technology | Package Manager | Features |
|------------|-----------------|----------|
| **React** | npm, pnpm, yarn, bun | React ecosystem grouping |
| **React Native** | npm, pnpm, yarn, bun | RN-specific dependencies |
| **Vue** | npm, pnpm, yarn, bun | Vue framework grouping |
| **TypeScript** | npm, pnpm, yarn, bun | Type definitions handling |
| **PNPM** | pnpm | Workspace support |
| **Bun** | bun | Native Bun packages |

**Total**: **14 technology stacks** supported out of the box.

---

## ⚙️ Configuration Details

### General Settings

| Setting | Value | Purpose |
|---------|-------|---------|
| **Timezone** | Europe/London | Consistent scheduling |
| **Schedule** | Weekends only | Minimize weekday noise |
| **Rate limit** | 2 PRs/hour | Avoid CI overload |
| **Concurrent PRs** | Max 5 | Balance updates vs review load |
| **Auto-merge** | Minor + patch | Safe automatic updates |
| **Labels** | Type-specific | Easy filtering |

### Update Behavior

**Minor & Patch Updates**:
```
v1.2.3 → v1.2.4 (patch)   ✅ Auto-merge
v1.2.3 → v1.3.0 (minor)   ✅ Auto-merge
```

**Major Updates**:
```
v1.2.3 → v2.0.0 (major)   ⚠️ Labeled "breaking", requires review
```

**Security Updates**:
```
Any version with CVE       🚨 Immediate, high priority
```

---

## 🎯 Technology-Specific Details

### Docker
```json
{
  "docker": {
    "digest": true,           // Security via digest pinning
    "minor": { "automerge": true }
  }
}
```

### Android/Gradle
```json
{
  "gradle": {
    "fileMatch": ["build.gradle", "build.gradle.kts"],
    "grouping": ["androidx", "com.google.android"]
  }
}
```

### Flutter/Dart
```json
{
  "flutter": {
    "enabled": true,
    "ignorePaths": ["ios/**", "android/**"]  // Focus on Dart deps
  }
}
```

### JavaScript/TypeScript
```json
{
  "npm": {
    "packageRules": [
      {
        "groupName": "React dependencies",
        "matchPackagePatterns": ["^react"]
      },
      {
        "groupName": "TypeScript definitions",
        "matchPackagePatterns": ["^@types/"]
      }
    ]
  }
}
```

---

## 💡 Customization

### Override Specific Settings

Add to your project's `renovate.json`:

```json
{
  "extends": ["github>SylphxAI/renovate-config"],
  "schedule": ["every weekend"],
  "labels": ["dependencies", "custom-label"],
  "prHourlyLimit": 5,
  "automerge": false  // Disable auto-merge for this project
}
```

### Add Project-Specific Rules

```json
{
  "extends": ["github>SylphxAI/renovate-config"],
  "packageRules": [
    {
      "matchPackageNames": ["critical-package"],
      "automerge": false,
      "labels": ["critical-review"]
    }
  ]
}
```

### Customize Schedule

```json
{
  "extends": ["github>SylphxAI/renovate-config"],
  "schedule": [
    "after 10pm on sunday",
    "before 6am on monday"
  ]
}
```

---

## 🔧 Advanced Usage

### Monorepo Support

Renovate automatically detects monorepos (PNPM workspaces, Lerna, Nx):

```json
{
  "extends": ["github>SylphxAI/renovate-config"],
  "packageRules": [
    {
      "matchPaths": ["packages/**"],
      "groupName": "monorepo packages"
    }
  ]
}
```

### Multiple Stack Projects

For projects using multiple stacks (e.g., React + Python):

```json
{
  "extends": ["github>SylphxAI/renovate-config"]
  // Auto-detection handles all stacks automatically
}
```

---

## 📊 Comparison with Default Renovate

| Feature | Default Renovate | This Config |
|---------|------------------|-------------|
| **Schedule** | Any time | ✅ Weekends only |
| **Auto-merge** | Manual config | ✅ Minor/patch by default |
| **Stack-specific** | Manual rules | ✅ 14 stacks auto-detected |
| **Grouping** | Basic | ✅ Smart framework groups |
| **Rate limiting** | None | ✅ 2 PRs/hour, 5 concurrent |
| **Labels** | Basic | ✅ Type-specific labels |

---

## 🛠️ Tech Stack

| Component | Technology |
|-----------|------------|
| **Tool** | Renovate Bot |
| **Config Format** | JSON5 |
| **Distribution** | GitHub repository |
| **Stacks Supported** | 14 (Docker, Android, iOS, Dart, React, Vue, etc.) |

---

## 🗺️ Roadmap

**✅ Completed**
- [x] Multi-stack support (14 stacks)
- [x] Auto-detection
- [x] Smart grouping
- [x] Weekend scheduling
- [x] Auto-merge minor/patch

**🚀 Planned**
- [ ] Go/Rust support
- [ ] .NET/C# support
- [ ] GitHub Actions workflow updates
- [ ] Custom preset variants (strict, relaxed)
- [ ] Vulnerability scanning integration

---

## 🤝 Contributing

Contributions are welcome! To add support for a new technology:

1. **Fork the repository**
2. **Add stack-specific rules** - Update `renovate.json`
3. **Test with sample project** - Verify auto-detection
4. **Document in README** - Add to supported stacks table
5. **Submit a pull request**

### Example: Adding New Stack

```json
{
  "packageRules": [
    {
      "description": "Go modules",
      "matchDatasources": ["go"],
      "groupName": "Go dependencies"
    }
  ]
}
```

---

## 🤝 Support

[![GitHub Issues](https://img.shields.io/github/issues/SylphxAI/renovate-config?style=flat-square)](https://github.com/SylphxAI/renovate-config/issues)

- 🐛 [Bug Reports](https://github.com/SylphxAI/renovate-config/issues)
- 💬 [Discussions](https://github.com/SylphxAI/renovate-config/discussions)
- 📧 [Email](mailto:hi@sylphx.com)
- 📖 [Renovate Docs](https://docs.renovatebot.com)

**Show Your Support:**
⭐ Star • 👀 Watch • 🐛 Report bugs • 💡 Suggest features • 🔀 Contribute

---

## 📄 License

MIT © [Sylphx](https://sylphx.com)

---

## 🙏 Credits

Built with:
- [Renovate](https://renovatebot.com) - Automated dependency updates
- Community contributions ❤️

Special thanks to the Renovate team for an amazing tool!

---

## 🔗 Related

- [Renovate Documentation](https://docs.renovatebot.com)
- [Renovate Configuration Options](https://docs.renovatebot.com/configuration-options/)
- [Renovate Presets](https://docs.renovatebot.com/presets/)

---

<p align="center">
  <strong>14 stacks. One config. Zero hassle.</strong>
  <br>
  <sub>Unified Renovate configuration that just works</sub>
  <br><br>
  <a href="https://sylphx.com">sylphx.com</a> •
  <a href="https://x.com/SylphxAI">@SylphxAI</a> •
  <a href="mailto:hi@sylphx.com">hi@sylphx.com</a>
</p>
