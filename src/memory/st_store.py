"""
Session base short term memory
"""

import json
from typing import Any
from infrastructure.config import ST_STORE_DIR
from uuid import uuid4
from datetime import datetime

class STStore:
    def __init__(self):
        self.session_id = uuid4()
        self.store = {}
        self.store_path = ST_STORE_DIR / f"{self.session_id}.json"
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        self._load()
    
    def _load(self) -> None:
        if self.store_path.exists():
            with open(self.store_path, "r") as f:
                self.store = json.load(f)
    
    def _save(self) -> None:
        with open(self.store_path, "w") as f:
            json.dump(self.store, f)
    
    def get(self, key: str) -> Any:
        return self.store.get(key)
    
    def set(self, key: str, value: Any) -> None:
        datetime = datetime.now().isoformat()
        self.store[key] = {"value": value, "timestamp": datetime}
        self._save()
    
    def delete(self, key: str) -> None:
        del self.store[key]
        self._save()
    
    def clear(self) -> None:
        self.store = {}
