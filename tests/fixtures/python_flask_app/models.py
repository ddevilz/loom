"""
Database models module
Demonstrates: classes, inheritance, type hints, properties
"""

from datetime import datetime
from enum import Enum


class UserRole(Enum):
    """User role enumeration"""

    ADMIN = "admin"
    USER = "user"
    GUEST = "guest"


class BaseModel:
    """Base model with common fields"""

    def __init__(self):
        self.created_at: datetime = datetime.utcnow()
        self.updated_at: datetime = datetime.utcnow()

    def update_timestamp(self) -> None:
        """Update the timestamp"""
        self.updated_at = datetime.utcnow()

    @property
    def age_seconds(self) -> float:
        """Get age in seconds"""
        return (datetime.utcnow() - self.created_at).total_seconds()


class Account(BaseModel):
    """Account model"""

    def __init__(self, account_id: int, name: str):
        super().__init__()
        self.account_id = account_id
        self.name = name
        self.balance: float = 0.0
        self.is_active: bool = True

    def deposit(self, amount: float) -> bool:
        """Deposit money"""
        if amount > 0:
            self.balance += amount
            self.update_timestamp()
            return True
        return False

    def withdraw(self, amount: float) -> bool:
        """Withdraw money"""
        if 0 < amount <= self.balance:
            self.balance -= amount
            self.update_timestamp()
            return True
        return False

    @property
    def status(self) -> str:
        """Get account status"""
        return "active" if self.is_active else "inactive"

    @classmethod
    def create_default(cls) -> "Account":
        """Create default account"""
        return cls(0, "Default Account")


class Transaction:
    """Transaction record"""

    def __init__(self, from_account: int, to_account: int, amount: float):
        self.from_account = from_account
        self.to_account = to_account
        self.amount = amount
        self.timestamp = datetime.utcnow()
        self.status = "pending"

    def complete(self) -> None:
        """Mark transaction as complete"""
        self.status = "completed"

    def cancel(self) -> None:
        """Cancel transaction"""
        self.status = "cancelled"
