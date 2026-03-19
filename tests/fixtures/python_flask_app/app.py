"""
Flask REST API Application - E2E Parser Test Fixture
Demonstrates: decorators, async functions, classes, type hints, imports
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
db = SQLAlchemy(app)
logger = logging.getLogger(__name__)


@dataclass
class UserDTO:
    """Data Transfer Object for User"""

    id: int
    username: str
    email: str
    created_at: datetime


class User(db.Model):
    """User model with authentication"""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password: str) -> None:
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify password"""
        return check_password_hash(self.password_hash, password)

    def to_dict(self) -> dict[str, any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "created_at": self.created_at.isoformat(),
        }


class BaseService:
    """Abstract base service class"""

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    def log_operation(self, operation: str) -> None:
        """Log service operation"""
        self.logger.info(f"Operation: {operation}")


class UserService(BaseService):
    """Service layer for user operations"""

    def __init__(self):
        super().__init__()
        self.cache: dict[int, User] = {}

    async def get_user_async(self, user_id: int) -> User | None:
        """Asynchronously fetch user"""
        await asyncio.sleep(0.1)  # Simulate async operation
        return User.query.get(user_id)

    def get_all_users(self) -> list[User]:
        """Get all users"""
        self.log_operation("get_all_users")
        return User.query.all()

    def create_user(self, username: str, email: str, password: str) -> User:
        """Create new user"""
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email format"""
        return "@" in email and "." in email.split("@")[1]

    @classmethod
    def from_config(cls, config: dict[str, any]) -> "UserService":
        """Create service from configuration"""
        instance = cls()
        return instance


# REST API Routes


@app.route("/api/users", methods=["GET"])
def get_users():
    """Get all users endpoint"""
    service = UserService()
    users = service.get_all_users()
    return jsonify([user.to_dict() for user in users])


@app.route("/api/users/<int:user_id>", methods=["GET"])
def get_user(user_id: int):
    """Get single user endpoint"""
    user = User.query.get_or_404(user_id)
    return jsonify(user.to_dict())


@app.route("/api/users", methods=["POST"])
def create_user():
    """Create user endpoint"""
    data = request.get_json()
    service = UserService()

    if not service.validate_email(data.get("email", "")):
        return jsonify({"error": "Invalid email"}), 400

    user = service.create_user(
        username=data["username"], email=data["email"], password=data["password"]
    )
    return jsonify(user.to_dict()), 201


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "timestamp": datetime.now(tz=timezone.utc).isoformat()})


async def async_background_task(user_id: int) -> None:
    """Async background task"""
    service = UserService()
    user = await service.get_user_async(user_id)
    if user:
        logger.info(f"Processed user: {user.username}")


def run_background_tasks() -> None:
    """Run background tasks"""
    asyncio.run(async_background_task(1))


if __name__ == "__main__":
    app.run(debug=True)
