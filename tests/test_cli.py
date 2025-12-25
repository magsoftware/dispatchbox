"""Tests for CLI module."""

import sys
from unittest.mock import MagicMock, Mock, call, patch

import psycopg2
import pytest

from dispatchbox.cli import (
    create_db_check_function,
    create_repository_factory,
    help,
    main,
    parse_args,
    setup_http_server,
    setup_logging,
)
from dispatchbox.http_server import HttpServer
from dispatchbox.repository import OutboxRepository


class TestParseArgs:
    """Tests for parse_args function."""

    def test_parse_args_with_required_dsn(self):
        """Test parse_args requires --dsn argument."""
        with patch("sys.argv", ["dispatchbox", "--dsn", "host=localhost dbname=test"]):
            args = parse_args()
            assert args.dsn == "host=localhost dbname=test"

    def test_parse_args_with_defaults(self):
        """Test parse_args uses default values."""
        from dispatchbox.config import (
            DEFAULT_BATCH_SIZE,
            DEFAULT_HTTP_HOST,
            DEFAULT_HTTP_PORT,
            DEFAULT_LOG_LEVEL,
            DEFAULT_NUM_PROCESSES,
            DEFAULT_POLL_INTERVAL,
        )

        with patch("sys.argv", ["dispatchbox", "--dsn", "host=localhost"]):
            args = parse_args()
            assert args.processes == DEFAULT_NUM_PROCESSES
            assert args.batch_size == DEFAULT_BATCH_SIZE
            assert args.poll_interval == DEFAULT_POLL_INTERVAL
            assert args.log_level == DEFAULT_LOG_LEVEL
            assert args.http_host == DEFAULT_HTTP_HOST
            assert args.http_port == DEFAULT_HTTP_PORT
            assert args.disable_http is False

    def test_parse_args_with_custom_values(self):
        """Test parse_args accepts custom values."""
        with patch(
            "sys.argv",
            [
                "dispatchbox",
                "--dsn",
                "host=localhost",
                "--processes",
                "8",
                "--batch-size",
                "50",
                "--poll-interval",
                "2.5",
                "--log-level",
                "DEBUG",
                "--http-host",
                "0.0.0.0",
                "--http-port",
                "9090",
            ],
        ):
            args = parse_args()
            assert args.processes == 8
            assert args.batch_size == 50
            assert args.poll_interval == 2.5
            assert args.log_level == "DEBUG"
            assert args.http_host == "0.0.0.0"
            assert args.http_port == 9090

    def test_parse_args_disable_http(self):
        """Test parse_args with --disable-http flag."""
        with patch("sys.argv", ["dispatchbox", "--dsn", "host=localhost", "--disable-http"]):
            args = parse_args()
            assert args.disable_http is True

    def test_parse_args_show_help(self):
        """Test parse_args with --show-help flag."""
        with patch("sys.argv", ["dispatchbox", "--dsn", "host=localhost", "--show-help"]):
            args = parse_args()
            assert args.show_help is True


class TestHelp:
    """Tests for help function."""

    @patch("dispatchbox.cli.argparse.ArgumentParser")
    def test_help_calls_print_help(self, mock_parser_class):
        """Test help function calls print_help."""
        mock_parser = Mock()
        mock_parser_class.return_value = mock_parser
        help()
        mock_parser.print_help.assert_called_once()


class TestSetupLogging:
    """Tests for setup_logging function."""

    @patch("dispatchbox.cli.logger")
    def test_setup_logging_removes_default_handler(self, mock_logger):
        """Test setup_logging removes default handler."""
        setup_logging("INFO")
        mock_logger.remove.assert_called_once()

    @patch("dispatchbox.cli.logger")
    @patch("dispatchbox.cli.sys.stderr")
    def test_setup_logging_adds_handler(self, mock_stderr, mock_logger):
        """Test setup_logging adds new handler."""
        setup_logging("DEBUG")
        assert mock_logger.add.call_count == 1
        call_args = mock_logger.add.call_args
        assert call_args[0][0] == mock_stderr
        assert call_args[1]["level"] == "DEBUG"
        assert call_args[1]["colorize"] is True

    @patch("dispatchbox.cli.logger")
    def test_setup_logging_configures_worker_name(self, mock_logger):
        """Test setup_logging configures worker name."""
        setup_logging("WARNING")
        mock_logger.configure.assert_called_once_with(extra={"worker": "main"})


class TestCreateDbCheckFunction:
    """Tests for create_db_check_function."""

    @patch("dispatchbox.cli.OutboxRepository")
    def test_create_db_check_function_returns_true_when_connected(self, mock_repo_class):
        """Test db check function returns True when connected."""
        mock_repo = Mock()
        mock_repo.is_connected.return_value = True
        mock_repo_class.return_value = mock_repo

        check_fn = create_db_check_function("host=localhost dbname=test")
        result = check_fn()

        assert result is True
        mock_repo.is_connected.assert_called_once()
        mock_repo.close.assert_called_once()

    @patch("dispatchbox.cli.OutboxRepository")
    def test_create_db_check_function_returns_false_when_not_connected(self, mock_repo_class):
        """Test db check function returns False when not connected."""
        mock_repo = Mock()
        mock_repo.is_connected.return_value = False
        mock_repo_class.return_value = mock_repo

        check_fn = create_db_check_function("host=localhost dbname=test")
        result = check_fn()

        assert result is False
        mock_repo.close.assert_called_once()

    @patch("dispatchbox.cli.OutboxRepository")
    def test_create_db_check_function_returns_false_on_psycopg2_error(self, mock_repo_class):
        """Test db check function returns False on psycopg2 error."""
        mock_repo_class.side_effect = psycopg2.OperationalError("Connection failed")

        check_fn = create_db_check_function("host=localhost dbname=test")
        result = check_fn()

        assert result is False

    @patch("dispatchbox.cli.OutboxRepository")
    def test_create_db_check_function_returns_false_on_value_error(self, mock_repo_class):
        """Test db check function returns False on ValueError."""
        mock_repo_class.side_effect = ValueError("Invalid DSN")

        check_fn = create_db_check_function("host=localhost dbname=test")
        result = check_fn()

        assert result is False

    @patch("dispatchbox.cli.OutboxRepository")
    def test_create_db_check_function_uses_correct_timeouts(self, mock_repo_class):
        """Test db check function uses correct timeouts."""
        mock_repo = Mock()
        mock_repo.is_connected.return_value = True
        mock_repo_class.return_value = mock_repo

        check_fn = create_db_check_function("host=localhost dbname=test")
        check_fn()

        mock_repo_class.assert_called_once_with("host=localhost dbname=test", connect_timeout=2, query_timeout=2)


class TestCreateRepositoryFactory:
    """Tests for create_repository_factory."""

    @patch("dispatchbox.cli.OutboxRepository")
    def test_create_repository_factory_returns_function(self, mock_repo_class):
        """Test factory returns a function."""
        factory = create_repository_factory("host=localhost dbname=test")
        assert callable(factory)

    @patch("dispatchbox.cli.OutboxRepository")
    def test_create_repository_factory_creates_new_repository(self, mock_repo_class):
        """Test factory creates new repository instance."""
        mock_repo = Mock()
        mock_repo_class.return_value = mock_repo

        factory = create_repository_factory("host=localhost dbname=test")
        repo1 = factory()
        repo2 = factory()

        assert mock_repo_class.call_count == 2
        assert repo1 == mock_repo
        assert repo2 == mock_repo

    @patch("dispatchbox.cli.OutboxRepository")
    def test_create_repository_factory_uses_correct_timeouts(self, mock_repo_class):
        """Test factory uses correct timeouts."""
        mock_repo = Mock()
        mock_repo_class.return_value = mock_repo

        factory = create_repository_factory("host=localhost dbname=test")
        factory()

        mock_repo_class.assert_called_with("host=localhost dbname=test", connect_timeout=2, query_timeout=5)


class TestSetupHttpServer:
    """Tests for setup_http_server function."""

    @patch("dispatchbox.cli.create_db_check_function")
    @patch("dispatchbox.cli.create_repository_factory")
    @patch("dispatchbox.cli.HttpServer")
    @patch("dispatchbox.cli.logger")
    def test_setup_http_server_when_enabled(
        self, mock_logger, mock_http_server_class, mock_repo_factory, mock_db_check
    ):
        """Test setup_http_server when HTTP is enabled."""
        mock_db_check_fn = Mock()
        mock_repo_fn = Mock()
        mock_db_check.return_value = mock_db_check_fn
        mock_repo_factory.return_value = mock_repo_fn

        mock_server = Mock()
        mock_http_server_class.return_value = mock_server

        args = Mock()
        args.disable_http = False
        args.dsn = "host=localhost dbname=test"
        args.http_host = "127.0.0.1"
        args.http_port = 8080

        result = setup_http_server(args)

        assert result == mock_server
        mock_http_server_class.assert_called_once_with(
            host="127.0.0.1",
            port=8080,
            db_check_fn=mock_db_check_fn,
            repository_fn=mock_repo_fn,
        )
        mock_server.start.assert_called_once()
        mock_logger.info.assert_called_once()

    def test_setup_http_server_when_disabled(self):
        """Test setup_http_server returns None when HTTP is disabled."""
        args = Mock()
        args.disable_http = True

        result = setup_http_server(args)

        assert result is None


class TestMain:
    """Tests for main function."""

    @patch("dispatchbox.cli.parse_args")
    @patch("dispatchbox.cli.help")
    @patch("dispatchbox.cli.setup_logging")
    @patch("dispatchbox.cli.setup_http_server")
    @patch("dispatchbox.cli.start_processes")
    @patch("dispatchbox.cli.logger")
    def test_main_with_show_help(
        self, mock_logger, mock_start_processes, mock_setup_http, mock_setup_logging, mock_help, mock_parse_args
    ):
        """Test main function with --show-help flag."""
        args = Mock()
        args.show_help = True
        args.log_level = "INFO"
        mock_parse_args.return_value = args

        main()

        mock_parse_args.assert_called_once()
        mock_help.assert_called_once()
        mock_setup_logging.assert_not_called()
        mock_start_processes.assert_not_called()

    @patch("dispatchbox.cli.parse_args")
    @patch("dispatchbox.cli.setup_logging")
    @patch("dispatchbox.cli.setup_http_server")
    @patch("dispatchbox.cli.start_processes")
    @patch("dispatchbox.cli.logger")
    def test_main_normal_execution(
        self, mock_logger, mock_start_processes, mock_setup_http, mock_setup_logging, mock_parse_args
    ):
        """Test main function normal execution."""
        args = Mock()
        args.show_help = False
        args.log_level = "INFO"
        args.processes = 4
        args.batch_size = 100
        args.poll_interval = 1.0
        args.dsn = "host=localhost dbname=test"
        mock_parse_args.return_value = args

        mock_http_server = Mock()
        mock_setup_http.return_value = mock_http_server

        main()

        mock_setup_logging.assert_called_once_with("INFO")
        mock_logger.info.assert_called_once()
        mock_start_processes.assert_called_once_with("host=localhost dbname=test", 4, 100, 1.0)
        mock_http_server.stop.assert_called_once()

    @patch("dispatchbox.cli.parse_args")
    @patch("dispatchbox.cli.setup_logging")
    @patch("dispatchbox.cli.setup_http_server")
    @patch("dispatchbox.cli.start_processes")
    @patch("dispatchbox.cli.logger")
    def test_main_stops_http_server_on_exception(
        self, mock_logger, mock_start_processes, mock_setup_http, mock_setup_logging, mock_parse_args
    ):
        """Test main function stops HTTP server even on exception."""
        args = Mock()
        args.show_help = False
        args.log_level = "INFO"
        args.processes = 4
        args.batch_size = 100
        args.poll_interval = 1.0
        args.dsn = "host=localhost dbname=test"
        mock_parse_args.return_value = args

        mock_http_server = Mock()
        mock_setup_http.return_value = mock_http_server
        mock_start_processes.side_effect = KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            main()

        mock_http_server.stop.assert_called_once()

    @patch("dispatchbox.cli.parse_args")
    @patch("dispatchbox.cli.setup_logging")
    @patch("dispatchbox.cli.setup_http_server")
    @patch("dispatchbox.cli.start_processes")
    @patch("dispatchbox.cli.logger")
    def test_main_without_http_server(
        self, mock_logger, mock_start_processes, mock_setup_http, mock_setup_logging, mock_parse_args
    ):
        """Test main function when HTTP server is disabled."""
        args = Mock()
        args.show_help = False
        args.log_level = "INFO"
        args.processes = 4
        args.batch_size = 100
        args.poll_interval = 1.0
        args.dsn = "host=localhost dbname=test"
        mock_parse_args.return_value = args

        mock_setup_http.return_value = None

        main()

        mock_start_processes.assert_called_once()
        # Should not raise AttributeError when http_server is None
