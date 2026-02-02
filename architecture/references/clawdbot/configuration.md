# Clawdbot Configuration Reference

## Overview

Configuration lives at `~/.clawdbot/clawdbot.json`. Missing config uses safe defaults.

---

## Minimal Configuration

```json
{
  "agent": {
    "model": "anthropic/claude-opus-4-5"
  }
}
```

---

## Full Configuration Structure

```json5
{
  // Agent defaults
  "agents": {
    "defaults": {
      // Model settings
      "model": {
        "primary": "anthropic/claude-opus-4-5",
        "fallbacks": ["anthropic/claude-sonnet-4", "openai/gpt-4o"]
      },

      // Thinking/reasoning
      "thinkingDefault": "high",  // off | minimal | low | medium | high | xhigh

      // Workspace
      "workspace": "~/clawd",
      "bootstrapMaxChars": 20000,
      "skipBootstrap": false,

      // Session behavior
      "session": {
        "scope": "per-sender",  // per-sender | per-channel-peer | per-peer
        "reset": {
          "mode": "daily",      // daily | idle
          "atHour": 4           // 0-23, local time
        }
      },

      // Compaction
      "compaction": {
        "memoryFlush": {
          "enabled": true,
          "softThreshold": 0.7
        }
      },

      // Context management
      "contextPruning": "adaptive",  // off | adaptive | aggressive

      // Sandbox
      "sandbox": {
        "mode": "non-main",     // off | non-main | all
        "scope": "session",     // session | agent | shared
        "docker": {
          "image": "clawdbot/sandbox:latest",
          "setupCommand": "apt-get update && apt-get install -y curl"
        }
      },

      // Heartbeat
      "heartbeat": {
        "enabled": true,
        "intervalMinutes": 30
      }
    },

    // Named agent configurations
    "list": [
      {
        "id": "work-agent",
        "identity": {
          "name": "WorkBot",
          "emoji": "💼"
        },
        "workspace": "~/work-clawd",
        "model": {
          "primary": "anthropic/claude-sonnet-4"
        }
      }
    ]
  },

  // Channel configurations
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "BOT_TOKEN",
      "dmPolicy": "pairing",    // pairing | open
      "allowFrom": ["+1234567890"],
      "historyLimit": 50,
      "dmHistoryLimit": 100
    },
    "discord": {
      "enabled": true,
      "token": "BOT_TOKEN",
      "dmPolicy": "pairing"
    },
    "whatsapp": {
      "enabled": true,
      "dmPolicy": "pairing"
    }
  },

  // Gateway settings
  "gateway": {
    "port": 18789,
    "host": "127.0.0.1",
    "auth": {
      "mode": "password",       // password | tailscale
      "password": "SECRET"
    },
    "tailscale": {
      "mode": "off"             // off | serve | funnel
    }
  },

  // Tool settings
  "tools": {
    "profile": "full",          // minimal | coding | messaging | full
    "elevated": {
      "allowFrom": {
        "telegram": ["+1234567890"],
        "discord": ["user#1234"]
      }
    }
  },

  // Skills settings
  "skills": {
    "load": {
      "extraDirs": ["/path/to/custom/skills"]
    },
    "entries": {
      "gmail": {
        "enabled": true,
        "apiKey": "GMAIL_TOKEN",
        "env": {
          "GMAIL_OAUTH_CLIENT": "..."
        }
      }
    }
  },

  // Hooks settings
  "hooks": {
    "internal": {
      "enabled": true,
      "entries": {
        "session-memory": { "enabled": true }
      }
    }
  },

  // Message settings
  "messages": {
    "responsePrefix": "[{model}] "
  }
}
```

---

## Key Configuration Sections

### agents.defaults.model

```json
{
  "model": {
    "primary": "anthropic/claude-opus-4-5",
    "fallbacks": [
      "anthropic/claude-sonnet-4",
      "openai/gpt-4o"
    ]
  }
}
```

Fallbacks activate on provider errors.

### agents.defaults.thinkingDefault

| Level | Description |
|-------|-------------|
| `off` | No extended thinking |
| `minimal` | Brief reasoning |
| `low` | Light thinking |
| `medium` | Moderate reasoning |
| `high` | Deep thinking (default) |
| `xhigh` | Maximum reasoning |

### agents.defaults.session

```json
{
  "session": {
    "scope": "per-sender",
    "reset": {
      "mode": "daily",
      "atHour": 4
    }
  }
}
```

| Scope | Behavior |
|-------|----------|
| `per-sender` | Each sender gets own session |
| `per-channel-peer` | Per sender per channel |
| `per-peer` | Shared across all channels |

### agents.defaults.sandbox

```json
{
  "sandbox": {
    "mode": "non-main",
    "scope": "session",
    "docker": {
      "image": "clawdbot/sandbox:latest"
    }
  }
}
```

| Mode | Behavior |
|------|----------|
| `off` | No sandboxing |
| `non-main` | Sandbox group/channel sessions |
| `all` | Sandbox everything |

### channels.<provider>

```json
{
  "telegram": {
    "enabled": true,
    "token": "BOT_TOKEN",
    "dmPolicy": "pairing",
    "allowFrom": ["+1234567890"],
    "historyLimit": 50
  }
}
```

| Policy | Behavior |
|--------|----------|
| `pairing` | Require approval code |
| `open` | Process all messages |

### tools.profile

| Profile | Tools Included |
|---------|----------------|
| `minimal` | read, write |
| `coding` | read, write, edit, bash |
| `messaging` | + sessions_* |
| `full` | All tools |

### tools.elevated

Elevated bash access per channel/user:

```json
{
  "elevated": {
    "allowFrom": {
      "telegram": ["+1234567890"],
      "discord": ["user#1234"]
    }
  }
}
```

---

## Environment Variables

### Model API Keys

```bash
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...
```

### Channel Tokens

```bash
TELEGRAM_BOT_TOKEN=...
DISCORD_BOT_TOKEN=...
```

### Skill-Specific

```bash
GMAIL_TOKEN=...
SPOTIFY_CLIENT_ID=...
```

---

## Command-Line Overrides

```bash
# Start with specific port
clawdbot gateway --port 18790

# Use specific model
clawdbot --model anthropic/claude-sonnet-4

# Enable verbose logging
clawdbot gateway --verbose

# Use specific config file
clawdbot --config /path/to/config.json
```

---

## Runtime Commands

### Configuration

```bash
/config show         # Show current config
/config set <path> <value>
/config apply        # Apply pending changes
```

### Model

```bash
/model               # Show current model
/model <name>        # Switch model
/model cycle         # Cycle through models
```

### Thinking

```bash
/thinking            # Show current level
/thinking high       # Set level
```

### Session

```bash
/new                 # New session
/reset               # Reset current
/status              # Show status
```

---

## Comparison to Pandora

| Aspect | Clawdbot | Pandora |
|--------|----------|---------|
| Config format | JSON | .env + Python |
| Location | `~/.clawdbot/` | Project `.env` |
| Hot reload | Yes | No |
| Multi-model | Built-in fallbacks | Single model |
| Per-user config | Via agents.list | N/A |
| Channel config | Per-platform | N/A |

### Lessons for Pandora

1. **Structured JSON config**: More flexible than flat .env
2. **Model fallbacks**: Auto-switch on errors
3. **Per-user settings**: Support multiple user profiles
4. **Runtime config**: Allow changing settings without restart
5. **Channel abstraction**: Prepare for multi-channel support
