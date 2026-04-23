"""
Utility functions module
Demonstrates: functions, type hints, decorators, lambda expressions
"""

import time
from collections.abc import Callable
from functools import wraps
<<<<<<< HEAD
from typing import Any, TypeVar
=======
from typing import Any, Generic, TypeVar
>>>>>>> main

T = TypeVar("T")


def timing_decorator(func: Callable) -> Callable:
    """Decorator to measure execution time"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        print(f"{func.__name__} took {end - start:.4f} seconds")
        return result

    return wrapper


def cache_decorator(func: Callable) -> Callable:
    """Simple cache decorator"""
    cache: dict[str, Any] = {}

    @wraps(func)
    def wrapper(*args):
        key = str(args)
        if key not in cache:
            cache[key] = func(*args)
        return cache[key]

    return wrapper


@timing_decorator
def process_data(data: list[int]) -> list[int]:
    """Process data with timing"""
    return [x * 2 for x in data if x > 0]


@cache_decorator
def fibonacci(n: int) -> int:
    """Calculate fibonacci number with caching"""
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)


def filter_and_map(
    data: list[int], filter_func: Callable[[int], bool], map_func: Callable[[int], int]
) -> list[int]:
    """Filter and map data"""
    return list(map(map_func, filter(filter_func, data)))


def create_multiplier(factor: int) -> Callable[[int], int]:
    """Create a multiplier function (closure)"""

    def multiply(x: int) -> int:
        return x * factor

    return multiply


class DataProcessor[T]:
    """Generic data processor"""

    def __init__(self):
        self.data: list[T] = []

    def add(self, item: T) -> None:
        """Add item to processor"""
        self.data.append(item)

    def process(self, func: Callable[[T], T]) -> list[T]:
        """Process all items"""
        return [func(item) for item in self.data]

    def filter(self, predicate: Callable[[T], bool]) -> list[T]:
        """Filter items"""
        return [item for item in self.data if predicate(item)]


async def async_fetch_data(url: str) -> dict[str, Any]:
    """Async data fetching"""
    import asyncio

    await asyncio.sleep(0.1)
    return {"url": url, "status": "success"}


async def async_process_batch(items: list[str]) -> list[dict[str, Any]]:
    """Process items asynchronously"""
    import asyncio

    tasks = [async_fetch_data(item) for item in items]
    return await asyncio.gather(*tasks)


def validate_input(min_val: int = 0, max_val: int = 100) -> Callable:
    """Parameterized decorator for input validation"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(value: int, *args, **kwargs):
            if not min_val <= value <= max_val:
                raise ValueError(f"Value must be between {min_val} and {max_val}")
            return func(value, *args, **kwargs)

        return wrapper

    return decorator


@validate_input(min_val=1, max_val=1000)
def calculate_square(n: int) -> int:
    """Calculate square with validation"""
    return n * n
