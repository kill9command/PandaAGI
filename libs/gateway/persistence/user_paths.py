"""
User Path Resolution Utility

Provides consistent path resolution for per-user data directories.
All user-specific data is stored under panda_system_docs/obsidian_memory/Users/{user_id}/.

Structure:
    panda_system_docs/obsidian_memory/
    ├── Meta/                           # GLOBAL — config, templates, schemas
    ├── Tools/                          # GLOBAL — tool documentation
    ├── README.md
    └── Users/
        └── default/
            ├── turns/                  # Conversation history
            ├── sessions/               # Session state
            ├── preferences.md          # User preferences
            ├── Projects/               # User projects
            ├── Knowledge/              # Per-user knowledge base
            │   ├── Research/
            │   ├── Products/
            │   ├── Concepts/
            │   ├── Facts/
            │   ├── Vendors/
            │   ├── Sites/
            │   ├── Topics/
            │   └── People/
            ├── Beliefs/                # Per-user beliefs
            ├── Improvements/           # Per-user improvement principles
            │   └── Principles/
            ├── Maps/                   # Per-user maps
            ├── Logs/                   # Per-user logs
            │   └── Changes/
            └── Indexes/                # Per-user indexes

Usage:
    from libs.gateway.persistence.user_paths import UserPathResolver

    resolver = UserPathResolver(user_id="default")
    turns_dir = resolver.turns_dir          # .../Users/default/turns
    knowledge_dir = resolver.knowledge_dir  # .../Users/default/Knowledge
"""

from pathlib import Path
from typing import Optional


class UserPathResolver:
    """
    Resolves paths for per-user data directories.

    Centralizes path computation to ensure consistency across all components.
    All memory categories (Knowledge, Beliefs, Maps, etc.) are per-user.
    Only Meta/ and Tools/ are global.
    """

    # Base paths
    SYSTEM_DOCS = Path("panda_system_docs")
    OBSIDIAN_MEMORY = SYSTEM_DOCS / "obsidian_memory"
    USERS_DIR = OBSIDIAN_MEMORY / "Users"
    DEFAULT_USER = "default"

    # Global paths (shared across all users)
    META_DIR = OBSIDIAN_MEMORY / "Meta"
    TOOLS_DIR = OBSIDIAN_MEMORY / "Tools"

    def __init__(self, user_id: Optional[str] = None):
        """
        Initialize with a user ID.

        Args:
            user_id: User identifier. Defaults to "default" if None or empty.
        """
        self.user_id = user_id if user_id else self.DEFAULT_USER
        self._user_dir = self.USERS_DIR / self.user_id

    # === Per-user directories ===

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

    @property
    def knowledge_dir(self) -> Path:
        """Per-user knowledge directory (Research, Products, Concepts, Facts, etc.)."""
        return self._user_dir / "Knowledge"

    @property
    def beliefs_dir(self) -> Path:
        """Per-user beliefs directory."""
        return self._user_dir / "Beliefs"

    @property
    def maps_dir(self) -> Path:
        """Per-user maps directory."""
        return self._user_dir / "Maps"

    @property
    def improvements_dir(self) -> Path:
        """Per-user improvements directory."""
        return self._user_dir / "Improvements"

    @property
    def logs_dir(self) -> Path:
        """Per-user logs directory."""
        return self._user_dir / "Logs"

    @property
    def indexes_dir(self) -> Path:
        """Per-user indexes directory."""
        return self._user_dir / "Indexes"

    def ensure_dirs(self) -> None:
        """Create all user directories if they don't exist."""
        self.turns_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        # Knowledge subdirs
        for subdir in ["Research", "Products", "Concepts", "Facts", "Vendors", "Sites", "Topics", "People"]:
            (self.knowledge_dir / subdir).mkdir(parents=True, exist_ok=True)
        self.beliefs_dir.mkdir(parents=True, exist_ok=True)
        self.maps_dir.mkdir(parents=True, exist_ok=True)
        (self.improvements_dir / "Principles").mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "Changes").mkdir(parents=True, exist_ok=True)
        self.indexes_dir.mkdir(parents=True, exist_ok=True)

    # === Class methods for static access without instantiation ===

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

    @classmethod
    def get_knowledge_dir(cls, user_id: Optional[str] = None) -> Path:
        """Get per-user knowledge directory."""
        uid = user_id if user_id else cls.DEFAULT_USER
        return cls.USERS_DIR / uid / "Knowledge"

    @classmethod
    def get_beliefs_dir(cls, user_id: Optional[str] = None) -> Path:
        """Get per-user beliefs directory."""
        uid = user_id if user_id else cls.DEFAULT_USER
        return cls.USERS_DIR / uid / "Beliefs"

    @classmethod
    def get_maps_dir(cls, user_id: Optional[str] = None) -> Path:
        """Get per-user maps directory."""
        uid = user_id if user_id else cls.DEFAULT_USER
        return cls.USERS_DIR / uid / "Maps"

    @classmethod
    def get_improvements_dir(cls, user_id: Optional[str] = None) -> Path:
        """Get per-user improvements directory."""
        uid = user_id if user_id else cls.DEFAULT_USER
        return cls.USERS_DIR / uid / "Improvements"

    @classmethod
    def get_logs_dir(cls, user_id: Optional[str] = None) -> Path:
        """Get per-user logs directory."""
        uid = user_id if user_id else cls.DEFAULT_USER
        return cls.USERS_DIR / uid / "Logs"

    @classmethod
    def get_indexes_dir(cls, user_id: Optional[str] = None) -> Path:
        """Get per-user indexes directory."""
        uid = user_id if user_id else cls.DEFAULT_USER
        return cls.USERS_DIR / uid / "Indexes"
