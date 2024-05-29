"""Contains classes that help with creating consistent system-level tests."""

from abc import ABC, abstractmethod


class TestFailure:
    """Base class for test failures."""

    def __init__(self, failure_description: str):
        """
        Initialize the TestFailure object.

        Args:
            failure_description: A short description of the failure.
        """
        self.failure_description = failure_description

    def __repr__(self) -> str:
        """
        Create a string representation of the TestFailure object.

        Returns: the string representation of the TestFailure object.
        """
        return f"{self.__class__.__name__}('{self.failure_description}')"


class LivenessFailure(TestFailure):
    """LivenessFailure class."""

    def __init__(self, failure_description: str):
        """
        Initialize the LivenessFailure object.

        Args:
            failure_description: A short description of the failure.
        """
        super().__init__(failure_description)


class ConsistencyFailure(TestFailure):
    """ConsistencyFailure class."""

    def __init__(self, failure_description: str):
        """
        Initialize the ConsistencyFailure object.

        Args:
            failure_description: A short description of the failure.
        """
        super().__init__(failure_description)


class SystemLevelTest(ABC):
    """
    Abstract base class for creating system level tests.

    Attributes:
        total_failures: The total number of test failures for a test run.
    """

    total_failures: [TestFailure] = []

    @abstractmethod
    async def run(self) -> None:
        """The method that runs the test, and needs to be implemented in a subclass."""
        raise NotImplementedError()

    def add_fault(self, fault: TestFailure) -> None:
        """
        Add a fault to the test failure list.

        Args:
            fault: The TestFailure object to add to the test failure list.
        """
        self.total_failures.append(fault)
