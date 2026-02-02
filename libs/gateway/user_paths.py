"""
User Path Resolution Utility

Provides consistent path resolution for per-user data directories.
All user-specific data is stored under panda_system_docs/obsidian_memory/Users/{user_id}/.

Structure:
    panda_system_docs/obsidian_memory/
    ├── Users/                          # Per-user data
    │   ├── user1/
    │   │   ├── turns/                  # Conversation history
    │   │   ├── sessions/               # Session state
    │   │   ├── transcripts/            # Chat transcripts
    │   │   ├── preferences.md          # User preferences
    │   │   └── Projects/               # User projects
    │   └── default/
    │       └── ...
    │
    ├── Knowledge/                      # SHARED across all users
    │   ├── Research/
    │   ├── Products/
    │   └── Concepts/
    │
    └── ... (other shared dirs)

Usage:
    from libs.gateway.user_paths import UserPathResolver

    resolver = UserPathResolver(user_id="user1")
    turns_dir = resolver.turns_dir      # panda_system_docs/obsidian_memory/Users/user1/turns
    sessions_dir = resolver.sessions_dir  # panda_system_docs/obsidian_memory/Users/user1/sessions
"""

from pathlib import Path
from typing import Optional


class UserPathResolver:
    """
    Resolves paths for per-user data directories.

    Centralizes path computation to ensure consistency across all components.
    """

    # Base paths
    SYSTEM_DOCS = Path("panda_system_docs")
    OBSIDIAN_MEMORY = SYSTEM_DOCS / "obsidian_memory"
    USERS_DIR = OBSIDIAN_MEMORY / "Users"
    DEFAULT_USER = "default"

    # Shared knowledge paths (not per-user)
    KNOWLEDGE_DIR = OBSIDIAN_MEMORY / "Knowledge"
    BELIEFS_DIR = OBSIDIAN_MEMORY / "Beliefs"
    MAPS_DIR = OBSIDIAN_MEMORY / "Maps"
    META_DIR = OBSIDIAN_MEMORY / "Meta"

    def __init__(self, user_id: Optional[str] = None):
        """
        Initialize with a user ID.

        Args:
            user_id: User identifier. Defaults to "default" if None or empty.
        """
        self.user_id = user_id if user_id else self.DEFAULT_USER
        self._user_dir = self.USERS_DIR / self.user_id

    @property
    def user_dir(self) -> Path:
        """Root directory for this user's data."""
        return self._user_dir

    @property
    def turns_dir(self) -> Path:
        """Directory for turn documents."""
        return self._user_dir / "turns"

    @property
    def sessions_dir(self) -> Path:
        """Directory for session data."""
        return self._user_dir / "sessions"

    @property
    def transcripts_dir(self) -> Path:
        """Directory for session transcripts."""
        return self._user_dir / "transcripts"

    @property
    def projects_dir(self) -> Path:
        """Directory for user projects."""
        return self._user_dir / "Projects"

    @property
    def preferences_file(self) -> Path:
        """Path to user preferences file."""
        return self._user_dir / "preferences.md"

    @property
    def memory_dir(self) -> Path:
        """Directory for user memory (legacy compatibility)."""
        return self._user_dir / "memory"

    def ensure_dirs(self) -> None:
        """Create all user directories if they don't exist."""
        self.turns_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    # Class methods for static access without instantiation

    @classmethod
    def get_turns_dir(cls, user_id: Optional[str] = None) -> Path:
        """Get turns directory for a user."""
        uid = user_id if user_id else cls.DEFAULT_USER
        return cls.USERS_DIR / uid / "turns"

    @classmethod
    def get_sessions_dir(cls, user_id: Optional[str] = None) -> Path:
        """Get sessions directory for a user."""
        uid = user_id if user_id else cls.DEFAULT_USER
        return cls.USERS_DIR / uid / "sessions"

    @classmethod
    def get_transcripts_dir(cls, user_id: Optional[str] = None) -> Path:
        """Get transcripts directory for a user."""
        uid = user_id if user_id else cls.DEFAULT_USER
        return cls.USERS_DIR / uid / "transcripts"

    @classmethod
    def get_projects_dir(cls, user_id: Optional[str] = None) -> Path:
        """Get projects directory for a user."""
        uid = user_id if user_id else cls.DEFAULT_USER
        return cls.USERS_DIR / uid / "Projects"

    @classmethod
    def get_preferences_file(cls, user_id: Optional[str] = None) -> Path:
        """Get preferences file for a user."""
        uid = user_id if user_id else cls.DEFAULT_USER
        return cls.USERS_DIR / uid / "preferences.md"

    @classmethod
    def get_memory_dir(cls, user_id: Optional[str] = None) -> Path:
        """Get memory directory for a user (legacy compatibility)."""
        uid = user_id if user_id else cls.DEFAULT_USER
        return cls.USERS_DIR / uid / "memory"

    # Shared paths (same for all users)

    @classmethod
    def get_knowledge_dir(cls) -> Path:
        """Get shared knowledge directory."""
        return cls.KNOWLEDGE_DIR

    @classmethod
    def get_research_dir(cls) -> Path:
        """Get shared research directory."""
        return cls.KNOWLEDGE_DIR / "Research"

    @classmethod
    def get_products_dir(cls) -> Path:
        """Get shared products knowledge directory."""
        return cls.KNOWLEDGE_DIR / "Products"

    @classmethod
    def get_concepts_dir(cls) -> Path:
        """Get shared concepts directory."""
        return cls.KNOWLEDGE_DIR / "Concepts"
