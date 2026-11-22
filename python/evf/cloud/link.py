"""The saved cloud link: ``cloud.json`` (base URL, device id, credential).

The credential is a secret. It's stored with mode 0600 and never logged or
sent to web clients (see ``CloudLink.public``).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

LINK_FILE = "cloud.json"


@dataclass(frozen=True)
class LinkInfo:
    base_url: str
    device_id: str
    credential: str
    paired_at: float
    name: str | None = None


class CloudLink:
    """Thread-safe holder of the current link, persisted next to config.json."""

    def __init__(self, directory: Path) -> None:
        self._path = Path(directory) / LINK_FILE
        self._lock = threading.Lock()
        self._info = self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> LinkInfo | None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return LinkInfo(
                base_url=str(data["base_url"]),
                device_id=str(data["device_id"]),
                credential=str(data["credential"]),
                paired_at=float(data.get("paired_at", 0)),
                name=data.get("name"),
            )
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Ignoring unreadable %s: %s", self._path.name, exc)
            return None

    def get(self) -> LinkInfo | None:
        with self._lock:
            return self._info

    @property
    def linked(self) -> bool:
        return self.get() is not None

    def save(self, info: LinkInfo) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(asdict(info), f, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
            self._info = info

    def set_name(self, name: str | None) -> None:
        info = self.get()
        if info is not None and info.name != name:
            self.save(LinkInfo(**{**asdict(info), "name": name}))

    def clear(self) -> None:
        with self._lock:
            self._info = None
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass

    def public(self) -> dict:
        """What the web UI may see: never the credential."""
        info = self.get()
        if info is None:
            return {"linked": False}
        return {
            "linked": True,
            "device_id": info.device_id,
            "name": info.name,
            "base_url": info.base_url,
            "paired_at": info.paired_at,
        }
