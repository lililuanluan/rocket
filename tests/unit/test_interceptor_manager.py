"""Tests for the InterceptorManager class."""

from unittest.mock import Mock, patch

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
