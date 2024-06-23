"""Tests for the InterceptorManager class."""

from subprocess import Popen, TimeoutExpired
from unittest.mock import MagicMock, Mock, patch

from docker.models.containers import Container

from xrpl_controller.interceptor_manager import InterceptorManager


def test_start_new():
    """Test starting a new interceptor."""
    with patch("xrpl_controller.interceptor_manager.Popen") as mock_popen:
        mock_popen.return_value.communicate.side_effect = lambda: (None, None)
        interceptor_manager = InterceptorManager()
        interceptor_manager.start_new()
        mock_popen.assert_called_once()


def test_restart_existing():
    """Test restarting an existing interceptor."""
    with patch("xrpl_controller.interceptor_manager.Popen") as mock_popen:
        mock_popen.return_value.communicate.side_effect = lambda: (None, None)
        interceptor_manager = InterceptorManager()
        interceptor_manager.start_new()
        interceptor_manager.restart()
        assert mock_popen.call_count == 2


def test_restart_not_started():
    """Test restarting an interceptor that has not been started."""
    with patch("xrpl_controller.interceptor_manager.Popen") as mock_popen:
        mock_popen.return_value.communicate.side_effect = lambda: (None, None)
        interceptor_manager = InterceptorManager()
        interceptor_manager.restart()
        assert mock_popen.call_count == 1


def test_stop_existing():
    """Test stopping an existing interceptor."""
    with patch("xrpl_controller.interceptor_manager.Popen") as mock_popen:
        mock_popen.return_value.communicate.side_effect = lambda: (None, None)
        interceptor_manager = InterceptorManager()
        interceptor_manager.start_new()
        interceptor_manager.stop()
        mock_popen.assert_called_once()


def test_stop_not_started():
    """Test stopping an interceptor that has not been started."""
    with patch("xrpl_controller.interceptor_manager.Popen") as mock_popen:
        mock_popen.return_value.communicate.side_effect = lambda: (None, None)
        interceptor_manager = InterceptorManager()
        interceptor_manager.stop()
        mock_popen.assert_not_called()


def test_check_output_with_stdout_stderr():
    """Test check_output method with stdout and stderr."""
    mock_popen = Mock()
    mock_popen.communicate.return_value = ("stdout", "stderr")
    with patch("xrpl_controller.interceptor_manager.Popen", return_value=mock_popen):
        interceptor_manager = InterceptorManager()
        interceptor_manager.start_new()
    mock_popen.communicate.assert_called_once()


def test_check_output_no_stdout_stderr():
    """Test check_output method without stdout and stderr."""
    mock_popen = Mock()
    mock_popen.communicate.return_value = (None, None)
    with patch("xrpl_controller.interceptor_manager.Popen", return_value=mock_popen):
        interceptor_manager = InterceptorManager()
        interceptor_manager.start_new()
    mock_popen.communicate.assert_called_once()


def test_cleanup_docker():
    """Test cleaning up docker containers."""
    mock_docker_client = Mock()
    mock_container1 = MagicMock(spec=Container)
    mock_container1.name = "validator_1"
    mock_container2 = MagicMock(spec=Container)
    mock_container2.name = "other_container"
    mock_container3 = MagicMock(spec=Container)
    mock_container3.name = "validator_2"

    mock_container1.stop = MagicMock(return_value=None)
    mock_container2.stop = MagicMock(return_value=None)
    mock_container3.stop = MagicMock(return_value=None)

    mock_docker_client.containers.list.return_value = [
        mock_container1,
        mock_container2,
        mock_container3,
    ]

    with patch("docker.from_env", return_value=mock_docker_client):
        interceptor_manager = InterceptorManager()
        interceptor_manager.cleanup_docker_containers()

    mock_container1.stop.assert_called_once()
    mock_container2.stop.assert_not_called()
    mock_container3.stop.assert_called_once()


def test_stop_ungraceful():
    """Test whether the stop behavior functions correctly on a timeout."""
    mock_popen = Mock(spec=Popen)
    mock_popen.communicate.return_value = (None, None)

    with patch("xrpl_controller.interceptor_manager.Popen") as mock_popen_class:
        mock_popen_class.return_value = mock_popen
        interceptor_manager = InterceptorManager()
        interceptor_manager.process = mock_popen

        mock_popen.wait.side_effect = TimeoutExpired(cmd="", timeout=5.0)

        interceptor_manager.stop()

        assert mock_popen.terminate.call_count == 1
        mock_popen.wait.assert_called_once_with(timeout=5.0)


@patch("xrpl_controller.interceptor_manager.exit", return_value=MagicMock())
def test_exception_behavior(exit_mock):
    """Test whether the exception behavior functions correctly."""
    with patch("xrpl_controller.interceptor_manager.Popen") as mock_popen_class:
        mock_popen_class.side_effect = FileNotFoundError()
        interceptor_manager = InterceptorManager()

        interceptor_manager.start_new()

        assert interceptor_manager.process is None
        assert exit_mock.call_count == 1
